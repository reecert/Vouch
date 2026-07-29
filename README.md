# vouch

Evidence-backed capability profiles for engineers, grounded in real commits and — with
consent — local session telemetry. Working name.

Built for **hiring teams screening candidates**: the profile's job is to tell a screener
what to ask, not to make the decision for them.

## The five layers

| Layer | What it does | Guarantee |
|---|---|---|
| **L1** `vouch/l1` | Git history → facts + confounds | Arithmetic only. Byte-reproducible; golden-file tested. |
| **L2** `vouch/l2` | Local session logs → derived metrics | Raw logs and source never leave the machine — the upload schema has no free-text field. |
| **L3** `vouch/l3` | Sessions ↔ commits | Runs locally. Three-valued: corroborated / ambiguous / uncorroborated. |
| **L4** `vouch/l4` | Diffs → dimension verdicts | `insufficient_evidence` is a schema enum, not a prompt request. Claims cite SHA **and** path. |
| **L5** `vouch/l5` + `web/` | Profile assembly → static report | Limitations are derived from confounds and absent layers, never volunteered by the model. |

## Design rules that are enforced, not aspired to

- **Denominators are visible, and floors suppress rather than round.** One fix commit
  cannot render as "100%".
- **Confounds can suppress a fact outright.** In a solo repo, ownership is `not_assessable`
  — fixing your own bugs is the only option available, so the measurement is meaningless.
- **No overall score.** `Profile` has no aggregate field; it is enforced by the type.
- **The support check only ever downgrades.** A bug in it makes a profile more cautious,
  never more flattering.

## Usage

```sh
vouch facts <repo> --author you@example.com        # L1 only: no LLM, no API key
vouch sessions --dry-run                            # L2: see exactly what would be uploaded
vouch profile <repo> --author you@example.com \
    --sessions payload.json --log-dir ~/.claude/projects
vouch eval --split holdout                          # score the judge against labels
```

## Status

L1–L5 are built and tested (416 tests, offline).

**The judge is uncalibrated.** `eval/labels.yaml` is empty, so nothing here licenses a
claim about how well its verdicts match human judgement. The harness refuses to print a
number rather than imply otherwise. See `docs/plan.md` §5.

Full plan, decisions and open questions: [`docs/plan.md`](docs/plan.md).
Competitor quality baseline: [`docs/baseline-competitor.md`](docs/baseline-competitor.md).
