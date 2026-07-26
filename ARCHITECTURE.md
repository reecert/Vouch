# vouch — Architecture (v0)

> Working name — rename freely. `vouch` = "attest to capability based on evidence."

## What this is

A tool that reads a git repository and produces an **evidence-backed capability report** for a
given engineer, grounded in real commits — not self-reported resume claims.

v0 proves exactly **one** capability dimension end-to-end: **ownership** — does this person return
to fix their own bugs, with tests, over time? If we can score *that* convincingly and know *why we
believe our own score*, everything else is the same machine pointed at a new dimension.

## Non-goals (v0)

- No web UI, no database, no auth, no queue.
- No multi-dimension scoring. Ownership only.
- No raw diffs sent to the model. Ever. (See "The one seam" below.)
- No self-hosted / fine-tuned model. Free-tier frontier API + local fallback.
- No private/enterprise repos. Public repos only (their content is already public → no leak risk,
  so free tiers that train on your data are fine here).

---

## The spine

```
ingest  ─►  extract  ─►  judge  ─►  report
(git)       (signals)     (LLM)      (JSON)
└── deterministic, cached ──┘   └─ stateless ─┘
```

**One rule governs the whole design:** the model appears at exactly one seam (`judge`).
Everything upstream is deterministic Python — reproducible, testable offline, cacheable. The model
reasons over facts we already computed; it never touches the repo directly.

Why this matters:
- **Anti-hallucination.** The judge cannot cite evidence it was never handed.
- **Scalability.** Deterministic extraction is parallel + cacheable; a stateless judge fans out
  trivially when it needs to. We don't build scale now — we avoid foreclosing it.
- **Testability.** Extractors are pure functions → ordinary unit tests, no LLM in the loop.

---

## Modules

Core is a **library** (`vouch/`). The CLI is a thin adapter over it. A future API or worker is
another thin adapter over the same core — not a rewrite.

### `ingest`
Clone/open a repo, pin a commit range, normalize into a `RepoSnapshot` (commits, per-commit file +
test-file touch metadata, blame lookups, PR refs if available). Pure git. Cached by `repo + HEAD SHA`.

### `extract`
Deterministic signal computation for the ownership dimension. Emits an `EvidenceBundle`: a set of
`Signal`s, each carrying its value **and the commit SHAs that back it**. This is where "no
hallucinated praise" is enforced structurally — the judge only ever sees these facts.

Ownership signals (each backed by SHAs):

| key                     | intuition                                                        | weight |
|-------------------------|------------------------------------------------------------------|--------|
| `returned_to_own_code`  | touched same files weeks later (sustained vs drive-by)           | high   |
| `fixed_own_bug`         | fix commit on code they authored (blame → same identity)         | high   |
| `tests_accompany_fixes` | fix commits that also add/modify test files                      | high   |
| `revert_recovery`       | reverted, then re-landed correctly                               | med    |
| `review_followthrough`  | responded to review with follow-up commits (if PR data present)  | med    |
| `commit_atomicity`      | focused, single-purpose commits (weak proxy)                     | low    |

### `judge`
The LLM adapter. Input: an `EvidenceBundle`. Output: a `Verdict` (score, calibrated confidence,
freshness, rationale citing SHAs). Provider-abstracted behind one `JudgeProvider` protocol with an
ordered **fallback chain** (see below). Stateless — a pure function of its input.

### `report`
Assemble `Verdict` + `EvidenceBundle` into a `CapabilityReport`; serialize to JSON (+ optional
markdown). Records `judge_model` and `prompt_version` so any report is reproducible.

### `eval` — the crux
A frozen, hand-labeled set of repos (known-strong / known-weak for ownership), split into
**train** (prompt iteration only) and **holdout** (final reported numbers). Runs the full
pipeline and scores the judge's output honestly *at the n we actually have*:

- **agreement** — verdict vs label, printed with its n.
- **confidence separation** — mean confidence on correct vs incorrect verdicts.
- **calibration** is deliberately **not** computed as a reliability curve at small n; it is
  reported as `insufficient_n`. We never claim "calibrated" on numbers that can't support it.

Guardrails baked in: the harness **refuses** to report holdout numbers when the holdout is
empty, and **warns loudly** when the total labeled corpus is < 15 (directional, not evidence).
The harness also does more than trust the judge — it re-runs the judge's own contracts
(malformed JSON, hallucinated SHAs → fail) and adds a **support check** that rejects a
grounded-but-inflated verdict (high score with no cited receipts / all-zero signals). Judge
calls are cached by evidence-bundle hash so re-running metrics re-burns no quota. If we can't
evaluate our own evaluator honestly, we've built a horoscope.

---

## Schemas (the core primitive)

The whole product reduces to one object: **claim + evidence + confidence + freshness.**

```python
class Signal(BaseModel):
    key: str                     # "fixed_own_bug"
    value: float | int | bool
    evidence: list[str]          # commit SHAs / PR refs — the receipts
    computed_at: datetime

class Verdict(BaseModel):
    dimension: str               # "ownership"
    score: float                 # 0..1
    confidence: float            # 0..1 — calibrated, not vibes
    freshness: date              # most recent supporting evidence
    rationale: str               # must reference cited SHAs
    cited_evidence: list[str]    # SHAs the model actually used

class CapabilityReport(BaseModel):
    repo: str
    subject: str                 # git author identity
    dimension: str
    verdict: Verdict
    evidence: list[Signal]
    judge_model: str             # provenance of the judgment itself
    prompt_version: str
    generated_at: datetime
```

---

## Robustness contracts (bake these in from commit 1)

1. **Determinism boundary.** AI only at `judge`. Everything upstream runs and is tested with no
   network.
2. **Evidence-grounding validator.** If `verdict.cited_evidence` contains any SHA not present in the
   input bundle → reject, retry once, then fail loud. Dishonesty fails a check; it isn't trusted
   away.
3. **Structured-output enforcement.** Request JSON → validate against Pydantic → on parse failure,
   one bounded retry feeding the error back → then fail loud. Never silently coerce.
4. **Provider fallback chain.** `JudgeProvider` protocol; ordered providers; on 429/error, retry the
   same call on the next provider rather than crashing.
5. **Caching.** `ingest` + `extract` cached by content hash. Re-running eval re-clones/re-parses
   nothing; only judge calls hit the network.
6. **Config over code.** Signal weights, thresholds, model choice, provider order, prompt live in
   versioned config. A report records the config + prompt version that produced it → reproducible.

---

## Provider chain (free-tier native)

Order (fail forward on rate-limit/error):

1. **Gemini (Google AI Studio free tier)** — frontier reasoning, ~1M-token context, no card.
   Primary judge.
2. **Groq (free)** — fast open-weight fallback for iteration.
3. **Ollama (local, `qwen2.5-coder`)** — offline $0 fallback; also the dev-loop model for plumbing.

Spend discipline: build + iterate entirely on free/local. Reserve a few dollars of a frontier API
(Claude/GPT) **only** for the final calibration run in `eval` — the one moment quality *is* the
question.

---

## Stack

- Python 3.12, `uv` (env + deps)
- `pydantic` v2 (schemas / validation)
- `git` via subprocess (or `GitPython`) for ingest
- `typer` (CLI)
- `pytest` (unit tests for extractors + the eval harness)
- Provider SDKs (`google-genai`, `groq`, `ollama`) behind the `JudgeProvider` adapter — thin.

---

## Layout

```
vouch/
  ingest/      # git → RepoSnapshot (deterministic, cached)
  extract/     # RepoSnapshot → EvidenceBundle (ownership signals)
  judge/       # EvidenceBundle → Verdict (LLM adapter + fallback chain)
  report/      # Verdict + evidence → CapabilityReport
  eval/        # labeled repos → judge-quality metrics  ← the crux
  schemas.py   # Signal, Verdict, CapabilityReport
  config.py    # weights, thresholds, provider order, prompt_version
cli.py         # thin typer wrapper over the library
tests/
  fixtures/    # small synthetic repos for deterministic extractor tests
eval/
  labels.yaml  # frozen hand-labeled repo set (strong/weak ownership)
```

## Scale path (later, no rewrite)

- Extraction parallelizes per-repo / per-author.
- Judge calls batch (batch APIs ~50% cheaper) and cache by evidence-bundle hash.
- Stateless judge → horizontal scale is trivial when traffic exists.
- CLI → FastAPI (on-demand) or worker (batch) = new adapter over the same core.
