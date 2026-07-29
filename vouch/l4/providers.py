"""Judge providers — the model behind L4, behind one swappable protocol.

`claude-opus-5` is the judge (docs/plan.md open question 5). Diff-level judgment is the
quality-critical seam of the product, and the v0 free-tier chain is not defensible here:
Gemini's free tier may train on submitted input, and L4 sends real diffs alongside derived
behavioural metrics about a named individual. Those providers remain available for local
development and are never the default.

The protocol takes a Pydantic type and returns an instance of it. That is deliberate: the
`insufficient_evidence` enum is enforced by the provider's structured-output mode, so a
response outside the schema is a transport error rather than something the orchestration
has to detect and re-prompt around.
"""
from __future__ import annotations

import os
from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

__all__ = [
    "DEFAULT_MODEL",
    "JudgeProvider",
    "ProviderError",
    "AnthropicProvider",
    "build_default_provider",
]

DEFAULT_MODEL = "claude-opus-5"

T = TypeVar("T", bound=BaseModel)


class ProviderError(Exception):
    """A recoverable transport/backend failure — the caller may fail forward."""


@runtime_checkable
class JudgeProvider(Protocol):
    """One LLM backend, returning schema-validated output."""

    name: str
    model: str

    def is_available(self) -> bool:
        """True if this provider can be called now (credentials present, SDK installed)."""
        ...

    def complete(self, system: str, user: str, schema: type[T]) -> T:
        """Send the prompt; return an instance of ``schema``.

        Raises :class:`ProviderError` on transport failure. Schema violations should not
        reach the caller — structured output is the provider's job.
        """
        ...


class AnthropicProvider:
    """Claude via the Anthropic SDK, using structured outputs.

    ``messages.parse`` constrains the response to the supplied Pydantic schema, which is
    how ``insufficient_evidence`` becomes unavoidable rather than merely requested: the
    model cannot emit a verdict outside the enum.

    Thinking is left at the Opus 5 default (adaptive, on by default) — this is exactly the
    kind of judgment that benefits from it, and pinning a budget here would be a guess.
    """

    def __init__(self, model: str = DEFAULT_MODEL, max_tokens: int = 8000) -> None:
        self.name = "anthropic"
        self.model = model
        self.max_tokens = max_tokens

    def is_available(self) -> bool:
        try:
            import anthropic
        except ImportError:
            return False
        # An unset ANTHROPIC_API_KEY is not proof of no credentials: the SDK reads a login too.
        try:
            anthropic.Anthropic()
        except Exception:
            return bool(os.getenv("ANTHROPIC_API_KEY"))
        return True

    def complete(self, system: str, user: str, schema: type[T]) -> T:
        try:
            import anthropic

            client = anthropic.Anthropic()
            response = client.messages.parse(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=schema,
            )
        except Exception as e:  # transport / rate limit / backend
            raise ProviderError(f"{self.name}: {e}") from e

        parsed = getattr(response, "parsed_output", None)
        if parsed is None:
            raise ProviderError(f"{self.name}: no parsed output in response")
        return parsed


def build_default_provider() -> JudgeProvider:
    """The production judge. Local-dev alternatives are wired explicitly, never by default."""
    return AnthropicProvider()
