# vouch documentation

Evidence-backed capability reports for engineers, grounded in real commits. v0 scores one
dimension end-to-end: **ownership**.

## Contents

| Page | What it covers |
| --- | --- |
| [Getting started](./getting-started.md) | Install, first run, `--evidence-only` |
| [Usage](./usage.md) | CLI reference, options, output formats |
| [Ownership signals](./signals.md) | How each signal is computed, thresholds, evidence |
| [The judge](./judge.md) | Provider chain, robustness contracts, prompt versioning |
| [Evaluating the judge](./eval.md) | Train/holdout split, honest metrics, adversarial mock |
| [Data model](./data-model.md) | `Signal`, `EvidenceBundle`, `Verdict`, `CapabilityReport` |
| [Configuration](./configuration.md) | Weights, thresholds, provider order, prompt version |
| [Development](./development.md) | Tests, fixtures, linting, CI/CD, releasing |
| [Architecture](../ARCHITECTURE.md) | Full design rationale (source of truth) |

## The one idea

The model appears at **exactly one seam** (`judge`). Everything upstream is deterministic
Python that runs and is tested with no network and no LLM. The judge reasons only over
pre-computed signals — never a diff, never the repo — and must cite its evidence by commit
SHA. A validator rejects any verdict that cites evidence it wasn't handed.

```
ingest  ─►  extract  ─►  judge  ─►  report
(git)       (signals)     (LLM)      (JSON)
└── deterministic, cached ──┘   └─ stateless ─┘
```
