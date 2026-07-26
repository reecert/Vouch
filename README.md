# vouch

**Evidence-backed capability reports for engineers, grounded in real commits — not resume claims.**

vouch reads a public git repository and scores one capability dimension for a given
author. v0 proves exactly one dimension end-to-end: **ownership** — *does this person
return to fix their own bugs, with tests, over time?*

Every claim is backed by commit SHAs. The language model never sees a diff or the repo —
only deterministic, pre-computed signals it must cite by SHA. A validator rejects any
verdict that cites evidence it wasn't handed.

> **Documentation:** start at [`docs/`](./docs/README.md) — getting started, usage,
> signals, the judge, data model, configuration, development.
> Full design rationale lives in [`ARCHITECTURE.md`](./ARCHITECTURE.md).

---

## The spine

```
ingest  ─►  extract  ─►  judge  ─►  report
(git)       (signals)     (LLM)      (JSON)
└── deterministic, cached ──┘   └─ stateless ─┘
```

**One rule governs the design:** the model appears at exactly one seam (`judge`).
Everything upstream is deterministic Python — reproducible, testable offline, cacheable.

- **Anti-hallucination** — the judge cannot cite evidence it was never handed; a validator
  enforces it.
- **Testability** — extractors are pure functions with ordinary unit tests, no LLM in the loop.
- **Reproducibility** — every report records the `judge_model` + `prompt_version` that produced it.

## Ownership signals (v0)

Each signal is deterministic and carries the commit SHAs that back it.

| signal | intuition | weight |
| --- | --- | --- |
| `returned_to_own_code` | touched the same files weeks later (sustained, not drive-by) | high |
| `fixed_own_bug` | fix commit on code they authored (blame → same identity) | high |
| `tests_accompany_fixes` | fix commits that also add/modify test files | high |
| `revert_recovery` | own code reverted, then re-landed | med |
| `commit_atomicity` | focused, single-purpose commits (weak proxy) | low |

> `review_followthrough` from the original design is **dropped in v0**: it needs GitHub
> PR/review data and is not derivable from pure git. Reserved for a later version.

---

## Install

Requires Python ≥ 3.12 and `git`.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # core + test tooling
pip install -e ".[providers]"    # optional: LLM provider SDKs (gemini/groq/ollama)
```

Provider SDKs are **optional** and lazy-imported — the deterministic core and the whole
test suite need none of them.

## Usage

```bash
# Full report (needs a judge provider configured — see below)
vouch run https://github.com/pallets/itsdangerous.git --author <author-email>

# Deterministic signals only — no LLM, runs anywhere, no keys needed
vouch run <repo_url> --author <email> --evidence-only

# Write JSON to a file and also print a markdown summary
vouch run <repo_url> --author <email> --out report.json --markdown
```

A local path works anywhere a URL does (handy for testing):

```bash
vouch run ./some/local/repo --author dev@example.com --evidence-only
```

### Evaluating the judge

Score the judge against the frozen labeled set (`eval/labels.yaml`, split into train/holdout):

```bash
vouch eval --split train              # iterate the prompt here (offline mock judge)
vouch eval --split holdout            # report final numbers (refuses if holdout is empty)
vouch eval --split holdout --live     # use the real provider chain (burns quota)
```

Reports **agreement** and **confidence separation**, each with its n; calibration is
`insufficient_n` until n is large (no reliability curve, no "calibrated" claim at small n).
Warns loudly below 15 labeled repos. Judge calls are cached by evidence-bundle hash, so
re-running metrics re-burns no quota. Full details: [docs/eval.md](./docs/eval.md).

### Configuring the judge

The judge tries providers in order and **fails forward** on rate-limit/error:

1. **Gemini** (Google AI Studio free tier) — `export GEMINI_API_KEY=...`
2. **Groq** (free) — `export GROQ_API_KEY=...`
3. **Ollama** (local, `qwen2.5-coder`) — run `ollama serve` locally

If none is available, `vouch run` fails loud with a clear message; use `--evidence-only`
to inspect the deterministic signals without a provider.

---

## How it stays honest

| contract | enforcement |
| --- | --- |
| **Determinism boundary** | AI only at `judge`; `ingest`/`extract` run and are tested with no network |
| **Evidence-grounding** | cited SHA not in the bundle → reject, retry once, then fail loud |
| **Structured output** | JSON → Pydantic → one bounded retry with the parse error fed back → fail loud |
| **Provider fallback** | on 429/error, retry the same call on the next provider |
| **Caching** | `ingest` cached by `repo + HEAD`; re-runs re-parse nothing |
| **Config over code** | weights, thresholds, provider order, `prompt_version` live in `vouch/config.py` |

## Development

```bash
pip install -e ".[dev]"
pytest                 # all tests run offline: no network, no LLM
ruff check .           # lint
```

Extractor tests build tiny synthetic git repos on the fly
(`tests/fixtures/builder.py`) so signal logic is exercised against real git behavior
without touching the network.

## Layout

```
vouch/
  ingest/      git → RepoSnapshot (deterministic, cached)
  extract/     RepoSnapshot → EvidenceBundle (ownership signals)
  judge/       EvidenceBundle → Verdict (LLM adapter + fallback chain)
  report/      Verdict + evidence → CapabilityReport
  eval/        labeled repos → judge-quality metrics
  schemas.py   Signal, Verdict, EvidenceBundle, CapabilityReport
  config.py    weights, thresholds, provider order, prompt_version
cli.py         thin typer wrapper over the library
tests/
  fixtures/    synthetic-repo builder for deterministic extractor tests
eval/
  labels.yaml  frozen hand-labeled repo set (strong/weak ownership)
```

## Status

v0, in progress. Phases 0–5 (investigation, schemas, deterministic core, judge, CLI, and the
eval harness) are complete and tested offline against an adversarial mock judge. The harness
reports agreement + confidence separation (calibration held at `insufficient_n`) over a
train/holdout split, with judge calls cached by evidence-bundle hash. Next: populate
`eval/labels.yaml` and run live for real numbers.
