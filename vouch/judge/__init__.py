"""judge — EvidenceBundle -> Verdict. The one seam where the model appears.

Stateless: a pure function of its input. Provider-abstracted behind ``JudgeProvider`` with
an ordered fallback chain (Gemini -> Groq -> Ollama). Three robustness contracts are
enforced here, never hoped for:

  * structured-output: JSON -> Pydantic -> one bounded retry with the parse error fed
    back -> fail loud. Never silently coerce.
  * evidence-grounding: any cited SHA not in the bundle -> reject, retry once, fail loud.
  * provider fallback: on 429/error, retry the same call on the next provider.

The prompt instructs the model to reason ONLY over provided signals and cite SHAs; it is
stored under ``config.prompt_version``.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Protocol, runtime_checkable

from pydantic import ValidationError

from vouch.config import (
    CONFIG,
    MAX_GROUNDING_RETRIES,
    MAX_STRUCTURED_RETRIES,
    PROVIDER_CHAIN,
    Config,
    ProviderSpec,
)
from vouch.judge.prompt import render_prompt
from vouch.schemas import EvidenceBundle, Verdict

__all__ = [
    "JudgeProvider",
    "ProviderError",
    "JudgeError",
    "judge",
    "render_prompt",
    "validate_grounding",
    "build_provider_chain",
    "GeminiProvider",
    "GroqProvider",
    "OllamaProvider",
]


@runtime_checkable
class JudgeProvider(Protocol):
    """Thin adapter over one LLM backend. Implementations: Gemini, Groq, Ollama."""

    name: str
    model: str

    def is_available(self) -> bool:
        """True if this provider can be called now (key present / server reachable)."""
        ...

    def complete_json(self, prompt: str) -> str:
        """Send ``prompt``, return the model's raw text (expected to be JSON).

        Raises ``ProviderError`` on 429/transport/backend failure so the chain can fail
        forward to the next provider.
        """
        ...


class ProviderError(Exception):
    """Recoverable provider failure — signals the chain to fail forward."""


class JudgeError(Exception):
    """Unrecoverable: retries exhausted, or every provider is down. Fail loud."""


# --------------------------------------------------------------------------------------
# Grounding + parsing
# --------------------------------------------------------------------------------------

_MIN_SHA_PREFIX = 7


def validate_grounding(verdict: Verdict, bundle: EvidenceBundle) -> list[str]:
    """Return any cited SHAs NOT present in the bundle. Empty list == grounded.

    A citation is grounded if it exactly matches, is a prefix of, or is prefixed by a SHA
    in the bundle's ``commit_index`` (models routinely cite short SHAs). Prefix matches
    must be at least ``_MIN_SHA_PREFIX`` chars to avoid coincidental collisions.
    """
    known = bundle.known_shas()
    ungrounded: list[str] = []
    for sha in verdict.cited_evidence:
        s = sha.strip()
        if s in known:
            continue
        if len(s) >= _MIN_SHA_PREFIX and any(
            k.startswith(s) or s.startswith(k) for k in known
        ):
            continue
        ungrounded.append(sha)
    return ungrounded


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t[t.find("\n") + 1 :] if "\n" in t else t[3:]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def _parse_verdict(raw: str) -> Verdict:
    """raw text -> Verdict. Raises ValueError (json) or ValidationError (schema)."""
    data = json.loads(_strip_fences(raw))
    return Verdict.model_validate(data)


# --------------------------------------------------------------------------------------
# The judge
# --------------------------------------------------------------------------------------


def _attempt(provider: JudgeProvider, bundle: EvidenceBundle, config: Config) -> Verdict:
    """One provider's full attempt: structured-output + grounding, with bounded retries.

    Propagates ``ProviderError`` (so the chain fails forward); raises ``JudgeError`` when
    parse or grounding retries are exhausted (fail loud — do not trust a bad verdict).
    """
    base = render_prompt(bundle, config)
    prompt = base
    parse_budget = MAX_STRUCTURED_RETRIES
    ground_budget = MAX_GROUNDING_RETRIES

    while True:
        raw = provider.complete_json(prompt)  # ProviderError propagates -> fail forward
        try:
            verdict = _parse_verdict(raw)
        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            if parse_budget > 0:
                parse_budget -= 1
                prompt = f"{base}\n\nYour previous reply failed to parse: {e}\nReturn ONLY valid JSON matching the schema."
                continue
            raise JudgeError(f"[{provider.name}] structured-output failed after retry: {e}") from e

        ungrounded = validate_grounding(verdict, bundle)
        if not ungrounded:
            return verdict
        if ground_budget > 0:
            ground_budget -= 1
            prompt = (
                f"{base}\n\nYour previous reply cited SHAs not in the evidence: "
                f"{ungrounded}\nCite ONLY SHAs listed in the commit index."
            )
            continue
        raise JudgeError(
            f"[{provider.name}] cited ungrounded SHAs after retry: {ungrounded}"
        )


def judge(
    bundle: EvidenceBundle,
    providers: list[JudgeProvider] | None = None,
    config: Config | None = None,
) -> tuple[Verdict, str]:
    """Judge ``bundle`` -> ``(Verdict, judge_model)``.

    Walks the provider chain; each provider enforces structured-output and grounding with
    bounded retries. On a provider transport error (429/etc) fails forward to the next.
    A parse/grounding exhaustion is fail-loud and is NOT retried on another provider —
    a dishonest or malformed verdict is a defect, not a routing problem.
    """
    config = config or CONFIG
    chain = providers if providers is not None else build_provider_chain(config)
    available = [p for p in chain if p.is_available()]
    if not available:
        raise JudgeError(
            "no judge provider available (set GEMINI_API_KEY / GROQ_API_KEY, or run Ollama)"
        )

    last_error: Exception | None = None
    for provider in available:
        try:
            verdict = _attempt(provider, bundle, config)
            return verdict, f"{provider.name}:{provider.model}"
        except ProviderError as e:
            last_error = e
            continue  # fail forward
    raise JudgeError(f"all providers failed; last error: {last_error}")


# --------------------------------------------------------------------------------------
# Concrete providers (thin; SDKs imported lazily so this module loads without them)
# --------------------------------------------------------------------------------------


class GeminiProvider:
    """Google AI Studio (free tier). Primary judge."""

    def __init__(self, model: str, api_key_env: str = "GEMINI_API_KEY") -> None:
        self.name = "gemini"
        self.model = model
        self.api_key_env = api_key_env

    def is_available(self) -> bool:
        if not os.getenv(self.api_key_env):
            return False
        try:
            import google.genai  # noqa: F401
        except ImportError:
            return False
        return True

    def complete_json(self, prompt: str) -> str:
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=os.environ[self.api_key_env])
            resp = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            return resp.text or ""
        except Exception as e:  # transport / rate-limit / backend -> fail forward
            raise ProviderError(f"gemini: {e}") from e


class GroqProvider:
    """Groq free tier. Fast open-weight fallback."""

    def __init__(self, model: str, api_key_env: str = "GROQ_API_KEY") -> None:
        self.name = "groq"
        self.model = model
        self.api_key_env = api_key_env

    def is_available(self) -> bool:
        if not os.getenv(self.api_key_env):
            return False
        try:
            import groq  # noqa: F401
        except ImportError:
            return False
        return True

    def complete_json(self, prompt: str) -> str:
        try:
            from groq import Groq

            client = Groq(api_key=os.environ[self.api_key_env])
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            raise ProviderError(f"groq: {e}") from e


class OllamaProvider:
    """Local Ollama. Offline $0 fallback + dev-loop model."""

    def __init__(self, model: str, host: str = "http://localhost:11434") -> None:
        self.name = "ollama"
        self.model = model
        self.host = host

    def is_available(self) -> bool:
        try:
            import ollama  # noqa: F401
        except ImportError:
            return False
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=1.0) as r:
                return r.status == 200
        except Exception:
            return False

    def complete_json(self, prompt: str) -> str:
        try:
            import ollama

            resp = ollama.Client(host=self.host).chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                format="json",
            )
            return resp["message"]["content"]
        except Exception as e:
            raise ProviderError(f"ollama: {e}") from e


def build_provider_chain(config: Config | None = None) -> list[JudgeProvider]:
    """Instantiate the ordered provider chain from config."""
    config = config or CONFIG
    out: list[JudgeProvider] = []
    for spec in config.provider_chain:
        out.append(_provider_from_spec(spec))
    return out


def _provider_from_spec(spec: ProviderSpec) -> JudgeProvider:
    if spec.name == "gemini":
        return GeminiProvider(spec.model, spec.api_key_env or "GEMINI_API_KEY")
    if spec.name == "groq":
        return GroqProvider(spec.model, spec.api_key_env or "GROQ_API_KEY")
    if spec.name == "ollama":
        return OllamaProvider(spec.model)
    raise ValueError(f"unknown provider: {spec.name}")


# keep the module-level PROVIDER_CHAIN reachable for callers/tests
_ = PROVIDER_CHAIN
