# Evaluating the judge

`eval` is the crux: it scores the judge against a frozen, hand-labeled set and reports how
good the judgments actually are — **honestly, at the n we have.** If we can't evaluate our
own evaluator, we've built a horoscope.

```bash
vouch eval --split train      # iterate the prompt here
vouch eval --split holdout    # report the final number here (once)
```

## The label set — `eval/labels.yaml`

Two disjoint pools, so the discipline is visible in the data itself:

```yaml
train:                        # the ONLY pool you may iterate the prompt against
  - repo: https://github.com/owner/name.git
    author: dev@example.com
    label: strong             # strong | weak
    reason: "returns Mar 2024 to fix Jan 2024 bug with tests (abc123)"
holdout:                      # read once, for the final reported metrics — never tune here
  - repo: https://github.com/other/thing.git
    author: someone@example.com
    label: weak
    reason: "single drive-by commit, never returns, no tests"
```

Every entry needs a **required, non-blank `reason`** — a one-line, falsifiable justification
drawn from the commits. A skeptic should be able to check it against the history. Loading
**fails loud** on: a missing/blank reason, an invalid label, a duplicated `(repo, author)`,
or a `(repo, author)` that appears in *both* pools (which would leak the holdout).

## Train / holdout discipline

- **train** — iterate the prompt here as much as you like.
- **holdout** — touch exactly once, for the final numbers. Tuning on it invalidates it.

The harness **refuses** (exit 1) to report holdout metrics when the holdout is empty — a
silent 0/0 would masquerade as a result. It **warns loudly** when the total labeled corpus
is below 15: numbers below that are *directional, not evidence*.

## Metrics — honest at this n

Every metric prints with its **n**. Numbers without an n are dishonest.

- **(a) agreement** — fraction of accepted verdicts whose strong/weak prediction (score vs
  the configured threshold) matches the label.
- **(b) confidence separation** — mean confidence on correct vs incorrect verdicts, and the
  gap between them. A judge that "knows when it's right" separates these.
- **calibration** — deliberately **not** computed as a reliability curve at small n. Reported
  as `insufficient_n` until n is large enough. We never print a curve or claim "calibrated"
  on numbers that can't support it.

## The harness does more than trust the judge

Each labeled repo runs the full pipeline (`ingest → extract → judge`) and lands in one of
four outcomes — all surfaced, never silently dropped:

| outcome | meaning | who caught it |
| --- | --- | --- |
| `scored` | accepted verdict; feeds the metrics | — |
| `judge_failed` | malformed JSON, or a hallucinated SHA not in the bundle | the judge's own contracts |
| `unsupported` | grounded but **inflated** — high score with no cited receipts / all-zero signals | the harness **support check** |
| `no_evidence` | no commits by the subject; nothing to judge | the harness |

The `unsupported` case matters most: a verdict can be schema-valid *and* grounded (it cites
nothing, so nothing is ungrounded) and still be a lie. Only the harness — which holds both
the verdict and the evidence bundle — can catch it. This is why the offline
[mock judge](../vouch/eval/mock.py) is **adversarial**: it can emit malformed JSON,
hallucinated SHAs, and inflated scores on demand, and the test suite asserts each one is
caught. A harness that only passes clean mocks is untested.

## Offline first, then live

- `--mock` (default) uses the offline adversarial mock — no keys, no network. Build and
  iterate here.
- `--live` uses the real provider chain (Gemini → Groq → Ollama). This burns quota; reserve
  it for the final calibration run.

Judge calls are **cached by evidence-bundle hash** (excluding volatile timestamps, keyed by
prompt version). Re-running metrics reads verdicts from disk and makes zero judge calls, so
you never re-burn quota on an unchanged bundle. `--no-cache` forces fresh calls.
