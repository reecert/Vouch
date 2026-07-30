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
separate Next.js 15 / React 19 / Tailwind 4 app: the product site and connect flow under
`app/(site)/`, and the L5 viewer at `/p/<id>` outside it, because a profile is read by
someone who was sent a link, not by a visitor browsing a site.

## Layers

| Layer | Module | Contract |
|---|---|---|
| L1 | `vouch/l1` | Git history → facts + confounds. Arithmetic only, byte-reproducible, golden-file pinned. |
| L2 | `vouch/l2` | Session logs → derived metrics. Raw logs never leave the machine; the payload schema has no free-text field. |
| L3 | `vouch/l3` | Sessions ↔ commits. Local. Three-valued: corroborated / ambiguous / uncorroborated. |
| L4 | `vouch/l4` | Diffs → dimension verdicts. `insufficient_evidence` is a schema enum, not a prompt request. Claims cite SHA **and** path. |
| L5 | `vouch/l5` | Profile assembly. Report + share link built. |

`vouch/pipeline.py` is the layer order, written once: `run_profile()` is what both the CLI
and the server worker call. A second transcription of it is how the two would silently
diverge. `vouch/serve` is the hosted path — `db.py` is the SQLite state the Next app shares
via `node:sqlite`, `worker.py` drains the job queue. Neither judges, extracts or renders.

`vouch/cli.py` is a thin typer adapter — all logic lives in `vouch/`. Commands: `facts`,
`profile`, `sessions`, `identity`, `label`, `eval`, `worker`.

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
- **One scanner decides what an address is: `vouch/privacy.py`.** Every guard imports
  `find_addresses`/`contains_address`; a second copy of that regex is how one of them
  silently stops catching. It discounts `userinfo@host` (`git@github.com:acme/api`,
  `https://tok:secret@host/p`) **positionally**, never by domain — a host we clone from must
  never reach the fixture-domain allowlist in `test_eval.py`, because allowlisting
  a host waves through every real mailbox served by it. An address in a URL *path* is still
  an address.
- **The repo address stops at ingest.** `RepoSnapshot.repo` is `repo_label(repo_url)`:
  `org/repo` for a remote, the **leaf alone** for a local path, because a local parent
  directory is where someone filed a clone (`~/clients/bigco/api`) and not who owns it. No
  home directory, no host, no credentials. The real address stays in-process as `repo_path`.
  `assert_no_machine_locals` (`tests/conftest.py`) scans finished documents against a fixed
  canary floor, because a judge that reads source can quote a path the normalizer never saw.
- **A stored `profile_id` must equal `compute_id()` of its own bytes.** Regenerate a
  snapshot; never hand-edit one and never edit the id to match.
- **A share link is immutable within a version, not forever.** `profile_id` hashes the
  document, so anything that moves the hashed payload — an L5 field, a new `Provenance`
  entry, a normalizer that rewrites a value — retires every link already sent. That is the
  accepted cost, not a bug to engineer around: a redirect map from retired ids would have to
  be maintained for the life of the product and it would publish the fact that two ids
  describe one subject, which is the disclosure an unlisted link exists to prevent. Bump the
  version, regenerate, re-share. `test_stored_id_reproduces` is what keeps the retirement
  loud instead of silent.
- **A hosted profile is git-only, structurally.** A server cannot read `~/.claude/projects`,
  so `vouch/serve/worker.py` passes no session evidence and the affected dimensions report
  `not_collected`. Do not add a way to upload logs to close that gap — the payload staying on
  the machine is the product, and "we could not look" must never render as "we looked".
- **Nothing from a browser becomes a git argument.** `/api/jobs` accepts a bare `owner/repo`
  matching `GITHUB_FULL_NAME`; the worker builds the URL. A path, an ssh address, an https
  URL or a leading `--` is refused at the door, and a test asserts the TypeScript and Python
  patterns are the same string.
- **Generated profiles never land in `web/data/profiles/`.** That directory is tracked and
  byte-pinned; real documents go to `var/` (gitignored). The split is also what keeps the
  revoke path unable to reach a checked-in sample. The git-only sample is rebuilt by
  `python scripts/build_sample_profiles.py`, never by hand — a filename that is a hash of
  the file's own bytes can only be corrected by regeneration.
- **Ownership is read from the session, never from the request.** Every route that touches a
  job filters on `user_id`; the 404 for someone else's job is the same as for a missing one.
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

cd web && npm run dev    # the site; needs web/.env.local for the connect flow
vouch worker             # drains queued jobs; nothing builds without it
```

## Tests

Named for the layer they cover. Every fact gets a positive **and** a discriminating negative
case. `tests/fixtures/builder.py` builds real synthetic git repos (author identity, dates,
touched files, revert bodies) — use it rather than mocking git. L4 tests drive scripted
providers, never a real LLM. `test_l1_golden.py` pins byte-identical output over eight
fixture repos; if a change moves golden output, that is the change under review.

`test_serve.py` runs the hosted path offline: `VOUCH_GIT_BASE` points at a local fixture, so
"clone `owner/repo` from GitHub" resolves without a network. The web half has no test
runner — the properties that matter there are asserted by reading the source from Python
(`test_web_share.py`), which is enough for a guard and not enough for behaviour.

## Docs

`docs/plan.md` is the current architecture and the open questions.
`docs/development.md` covers setup, labelling, CI/CD, release.
`docs/baseline-competitor.md` is the competitor quality baseline.
