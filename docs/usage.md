# Usage

vouch is a thin CLI over a library. All logic lives in `vouch/`; the CLI (`cli.py`) only
wires the pipeline together.

## Commands

```
vouch run  REPO_URL --author EMAIL [options]   # one author -> a report
vouch eval [--labels PATH] [--split ...]        # score the judge against labels
```

`run` executes `ingest → extract → judge → report` for one author. `eval` scores the judge
against the frozen labeled set — see [Evaluating the judge](./eval.md).

### Arguments

| Argument | Description |
| --- | --- |
| `REPO_URL` | Public git repo URL, or a local path to a git repo. |

### Options

| Option | Description |
| --- | --- |
| `--author EMAIL` | **Required.** The git author email to evaluate. |
| `--evidence-only` | Skip the LLM judge; emit just the deterministic `EvidenceBundle` JSON. |
| `--out PATH` | Write the JSON report to `PATH` instead of stdout. |
| `--markdown` | Also print a human-readable markdown summary. |

## Examples

```bash
# Deterministic signals only — no keys, runs anywhere
vouch run <repo> --author dev@example.com --evidence-only

# Full report to stdout (needs a judge provider)
vouch run <repo> --author dev@example.com

# Write JSON to a file and print a markdown summary too
vouch run <repo> --author dev@example.com --out report.json --markdown
```

## Output

### `--evidence-only`

Prints an [`EvidenceBundle`](./data-model.md#evidencebundle): the subject, the activity
window, the five signals (each with backing SHAs), and a `commit_index` mapping every
cited SHA to human-readable metadata (date, subject line, file count, whether tests were
touched). No diffs — ever.

### Full report

Prints (or writes, with `--out`) a [`CapabilityReport`](./data-model.md#capabilityreport):
the `EvidenceBundle`'s signals plus the judge's `Verdict` (score, calibrated confidence,
freshness, rationale, cited SHAs) and full provenance (`judge_model`, `prompt_version`,
`generated_at`).

With `--markdown`, a summary like:

```markdown
# Ownership report — dev@example.com

- **Repo:** https://github.com/owner/name.git
- **Score:** 0.78  ·  **Confidence:** 0.61  ·  **Freshness:** 2025-06-14
- **Judge:** gemini:gemini-2.0-flash  ·  **Prompt:** ownership-v0
...
```

## `vouch eval`

Scores the judge against `eval/labels.yaml`. See [Evaluating the judge](./eval.md) for the
train/holdout discipline, the honest-at-small-n metrics, and the adversarial mock. Quick form:

```bash
vouch eval --split train              # iterate the prompt here (offline mock judge)
vouch eval --split holdout            # report final numbers here
vouch eval --split holdout --live     # use the real provider chain (burns quota)
vouch eval --no-cache                 # ignore the bundle-hash judge cache
```

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success. |
| `1` | Judge failed, or `eval` refused (e.g. empty holdout). |
| `2` | `eval` label file invalid (missing reason, bad label, holdout leak). |

A zero-commit author is a warning (to stderr) for `run`; in `eval` it is a per-repo
`no_evidence` outcome that is surfaced, not scored. It is never silently counted as correct.
