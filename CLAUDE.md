# CLAUDE.md

## Working rules

- **No shortcuts. No band-aids.** Every solution must be robust, clean, scalable, and
  maintainable. If the right fix is harder, do it right. Flag complexity but don't cut
  corners.
- **Verify before implementing.** Before writing code for any non-trivial pattern, consult
  official docs or well-established resources. Do not rely on training memory for API
  signatures, config options, or library behaviour — these change.
- **No AI slop.** No generic boilerplate, copy-paste patterns, or filler code that "looks
  right." Every line must have a reason. Prefer explicit over implicit, specific over
  generic.

### Comments

- One line max. Never explain what the code does — only *why* it does it if the reason is
  non-obvious.
- Never comment on well-known library defaults, standard patterns, or config values
  documented upstream.
- No block comments above constants or config objects.

Module docstrings are the exception and are where the reasoning lives (see
`vouch/l4/schema.py`): they explain why a shape was chosen, not what it contains. A design
argument that outgrows one line belongs there, not above the constant it concerns. In
`eval/*.yaml`, which has no docstring, the file header comment plays that role.

A threshold or schema field that needs a reason takes a trailing one-liner:
`return_gap_days: int = 14  # sooner than this, a self-fix is the same session finishing`.

## What this is

`vouch` builds evidence-backed capability profiles for engineers from real git history and,
with consent, local Claude Code session logs. Audience: hiring screeners. The profile tells
them what to ask; it does not decide.

Python 3.12+, `pydantic` + `typer` + `pyyaml`. Provider SDKs (`anthropic`) are an optional
extra — the deterministic core and the whole test suite need none of them. `web/` is a
separate Next.js 15 / React 19 / Tailwind 4 app for L5 rendering.

## Layers

| Layer | Module | Contract |
|---|---|---|
| L1 | `vouch/l1` | Git history → facts + confounds. Arithmetic only, byte-reproducible, golden-file pinned. |
| L2 | `vouch/l2` | Session logs → derived metrics. Raw logs never leave the machine; the payload schema has no free-text field. |
| L3 | `vouch/l3` | Sessions ↔ commits. Local. Three-valued: corroborated / ambiguous / uncorroborated. |
| L4 | `vouch/l4` | Diffs → dimension verdicts. `insufficient_evidence` is a schema enum, not a prompt request. Claims cite SHA **and** path. |
| L5 | `vouch/l5` | Profile assembly. Report + share link not built. |

`vouch/cli.py` is a thin typer adapter — all logic lives in `vouch/`. Commands: `facts`,
`profile`, `sessions`, `identity`, `label`, `eval`.

## Invariants — do not regress these

- **No overall score.** `Profile` has no aggregate field; the type enforces it.
- **Denominators stay visible; floors suppress rather than round.** One fix commit cannot
  render as "100%".
- **Confounds suppress facts outright.** Solo repo → ownership is `not_assessable`, because
  the measurement is meaningless there.
- **The support check only ever downgrades.** A bug in it must make a profile more cautious,
  never more flattering.
- **No address is ever written to a tracked file.** `eval/repos.yaml` stores a selector
  (author rank + digest), resolved against the clone at run time. `load_labels` scans the
  raw file for anything email-shaped and refuses to load. CI checks out at `fetch-depth: 0`
  so the privacy test scans the whole history.
- **`eval/labels.yaml` is tracked and empty**, and a test keeps it that way. Real labelling
  writes `eval/labels.local.yaml` (gitignored). While it is empty, nothing here licenses a
  claim about judge accuracy.
- **Labelling is blind.** `build_task` takes L1 + L3 only and has no parameter an L4 finding
  could arrive through. The split is a hash of `(corpus_id, dimension)`, decided before the
  evidence is drawn.

## Version constants

Bump when the thing they describe changes — a stale key serves wrong cached data:

- `EXTRACTOR_VERSION` (`vouch/l1/cache.py`) — **whenever L1's computation changes**: a new
  predicate, a changed blame rule, a different interval. `SCHEMA_VERSION` (`l1/facts.py`)
  describes output *shape* only, and a change to what `ownership_loop` counts leaves the
  shape identical and every cached value wrong.
- `PROMPT_VERSION` (`l4/prompt.py`), `L4_SCHEMA_VERSION` (`l4/schema.py`),
  `PAYLOAD_SCHEMA_VERSION` (`l2/payload.py`), `PARSER_VERSION`, `SNAPSHOT_VERSION`,
  `RENDER_VERSION`, `IDENTITY_SCHEMA_VERSION`.

## Commands

```bash
pip install -e ".[dev]"
pytest -q          # entire suite is offline: no network, no providers installed
ruff check .       # E, F, I, UP, B; line-length 100, E501 ignored
```

## Tests

Named for the layer they cover. Every fact gets a positive **and** a discriminating negative
case. `tests/fixtures/builder.py` builds real synthetic git repos (author identity, dates,
touched files, revert bodies) — use it rather than mocking git. L4 tests drive scripted
providers, never a real LLM. `test_l1_golden.py` pins byte-identical output over eight
fixture repos; if a change moves golden output, that is the change under review.

## Docs

`docs/plan.md` is the current architecture and the open questions.
`docs/development.md` covers setup, labelling, CI/CD, release.
`docs/baseline-competitor.md` is the competitor quality baseline.
