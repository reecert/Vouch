# The judge

The judge is the **one seam** where a language model appears. It is stateless — a pure
function of its input `EvidenceBundle` — and it never sees a diff or the repo, only the
pre-computed signals and the SHA-anchored `commit_index`.

```
EvidenceBundle ─► judge ─► (Verdict, "provider:model")
```

## Provider chain

Providers are tried in order and **fail forward** on rate-limit/transport errors:

| # | Provider | Default model | Credential |
| --- | --- | --- | --- |
| 1 | **Gemini** (Google AI Studio free tier) | `gemini-2.0-flash` | `GEMINI_API_KEY` |
| 2 | **Groq** (free) | `llama-3.3-70b-versatile` | `GROQ_API_KEY` |
| 3 | **Ollama** (local) | `qwen2.5-coder` | none — run `ollama serve` |

Each provider is a thin adapter implementing the `JudgeProvider` protocol
(`is_available()`, `complete_json(prompt)`). SDKs are **lazy-imported**, so the module
loads even with no SDKs installed; `is_available()` returns `False` when the key is missing
or the SDK/server is absent.

The order, models, and credentials come from `PROVIDER_CHAIN` in
[`vouch/config.py`](./configuration.md).

## Robustness contracts

These are enforced in code and covered by tests — not hoped for.

### 1. Structured output

The model is asked for JSON. The judge parses it into a `Verdict` (Pydantic). On a parse
failure it retries **once**, feeding the parse error back into the prompt. If it still
fails, it raises `JudgeError` — it never silently coerces a malformed reply.

### 2. Evidence grounding

Every SHA in `verdict.cited_evidence` must correspond to a SHA in the bundle's
`commit_index` (exact or prefix match, ≥ 7 chars — models often cite short SHAs). If any
citation is ungrounded, the judge retries **once**, telling the model which SHAs were
invalid. If it still cites phantom evidence, it raises `JudgeError`.

> A dishonest or malformed verdict is treated as a **defect**, not a routing problem — it
> is *not* retried on a different provider. Only transport errors fail forward.

### 3. Provider fallback

On a `ProviderError` (429 / transport / backend failure), the judge moves to the next
available provider. If every provider is unavailable or errors, it raises `JudgeError`.

## Prompt versioning

The prompt lives in `vouch/judge/prompt.py` and is stamped with `config.prompt_version`
(currently `ownership-v0`). The prompt:

- states the model has **not** seen diffs or the repo;
- lists the signals with their weights and backing SHAs;
- includes the `commit_index` as the only SHAs it may cite;
- demands a strict JSON `Verdict` with a rationale that references SHAs.

Every report records the `judge_model` and `prompt_version` that produced it, so any
verdict is reproducible.

## Failure, by design

In an environment with no keys and no Ollama, `judge()` raises:

```
JudgeError: no judge provider available (set GEMINI_API_KEY / GROQ_API_KEY, or run Ollama)
```

Use `vouch run ... --evidence-only` to inspect the deterministic signals without a
provider.
