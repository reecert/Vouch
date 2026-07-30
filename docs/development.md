# Development

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Tests

The **entire** suite runs offline — no network, no LLM providers installed.

```bash
pytest -q
```

Tests are named for the layer they cover.

- **`test_ingest.py`** — git parsing, snapshot caching, revert-body parsing, blame.
- **`test_l1_*.py`** — facts, confound detection, identity/mailmap resolution, path
  classification. Each fact gets a positive and a discriminating negative case.
  `test_l1_golden.py` pins byte-identical output over eight fixture repos; `test_l1_cache.py`
  covers the persistence cache, including that every input which changes the facts also
  changes the key.
- **`test_l2_*.py`** — the JSONL parser (including mutated and non-session logs), derived
  metrics, and the payload-closure test that walks the *schema* and fails on any free-text
  field. `test_l2_snapshot.py` covers session identity and reproducibility: subagent
  transcripts are not sessions, and the logs are read from a snapshot so a run does not
  observe its own writes and mint a different `profile_id`.
- **`test_l3_*.py`** — the session↔commit join, its measured precision/recall harness, and
  repo identity.
- **`test_l4_*.py`** — structured-output and grounding retries, the support check and the
  adversarial mock modes, driven by scripted providers (no real LLM).
- **`test_l5_profile.py`** — profile assembly and the frozen snapshot.
- **`test_evidence_strength.py`** — intervals, asymmetric evidence requirements and
  evidence-led ordering. The largest file in the suite, because the failure it guards
  against (a damning number that cleared every symmetric floor) is the one nobody in the
  loop is motivated to catch.
- **`test_scoping.py`** — a metric is only evidence for the population it measured: L2 reads
  every project on the machine, L1 and L3 read one repository, and a profile headed with one
  repo's name must not publish a rate dominated by unrelated work.
- **`test_serve.py`** — the hosted path offline. Atomic job claiming, a server-side profile
  that is git-only by construction, and a failure that renders as a sentence.
  `VOUCH_GIT_BASE` points at a local fixture, so "clone `owner/repo`" resolves with no
  network.
- **`test_web_share.py`** — share metadata and the documents it must not disturb: the
  snapshot bytes, the ids they resolve at, and the *shape* of the hashed payload. The web
  half has no test runner, so the properties that matter there are asserted by reading the
  TypeScript from Python — enough for a guard, not enough for behaviour.
- **`test_eval*.py`, `test_labeling.py`** — the eval harness, the corpus and its
  address-free selectors, and the blind labelling procedure (§ *Labelling the corpus*).
  `TestLabelPrivacy` scans **every blob in the history**, not the working tree, which is why
  CI checks out at `fetch-depth: 0`.
- **`test_privacy.py`** — the one address scanner every guard above imports, and the pair it
  exists to keep apart: `git@github.com:acme/api` is URL authority, `alice@corp.example` in
  a URL *path* is still an address.
- **`test_cli.py`** — CLI wiring via `typer`'s `CliRunner`; the judge is monkeypatched, and
  `facts` exercises the deterministic path with no patching.

### Fixtures

`tests/fixtures/builder.py` builds tiny synthetic git repos on the fly with full control
over author identity, dates, touched files, and revert bodies — the exact axes the signals
key off. This exercises real `git` behavior without touching the network.

```python
from tests.fixtures.builder import ALICE, Step, build_repo

shas = build_repo(tmp_path / "r", [
    Step(ALICE, "T1", "add", {"a.py": "1\n"}),
    Step(ALICE, "T2", "fix a", {"a.py": "2\n"}),
])
```

## Labelling the corpus

`eval/labels.yaml` is tracked and **empty**, and a test keeps it that way — it is the
schema contract, and while it is empty nothing in this repository licenses a claim about
the judge's accuracy. Real labelling writes to `eval/labels.local.yaml`, which is
gitignored.

```bash
vouch label                      # every unlabelled (corpus row, dimension) pair
vouch label --only wagtail-contrib --limit 4
```

Each task prints the deterministic evidence for one dimension of one corpus row, then asks
for a verdict. Four properties are enforced by the tool rather than left to whoever is
labelling:

- **It is blind.** `build_task` takes L1 and L3 only and has no parameter an L4 finding
  could arrive through. Shown a model's verdict first, a human agrees with it far more
  often than they otherwise would, and the eval then measures how persuasive the judge is
  rather than how right it is.
- **The split is decided before the evidence is drawn** — a hash of
  `(corpus_id, dimension)`, so it cannot be re-rolled and a holdout cannot be chosen after
  the fact. Per pair rather than per repo, so no one history lands wholly on one side.
- **Thin facts are rendered as intervals.** `0/5` is shown as the range it is, so the
  person writing ground truth cannot read it as a zero either.
- **No address is written down.** A label is keyed on a corpus id;
  [`eval/repos.yaml`](../eval/repos.yaml) stores a *selector* (author rank plus a digest of
  the address) and resolves it against the clone at run time. `load_labels` scans the raw
  file for anything email-shaped — including in a hand-written `reason` — and refuses to
  load if it finds one. What counts as email-shaped is decided in one place,
  `vouch/privacy.py`, which discounts `userinfo@host` by position rather than by domain: a
  scanner that reads `git@github.com:acme/api` as an address gets "fixed" by allowlisting
  `github.com`, and that allowlist entry is what a real address then walks through.

`insufficient_evidence` is a first-class answer and is expected to be common. A corpus of
only conclusive labels would teach nothing about overclaiming, which is the failure the
whole quality bar exists to catch.

### The L1 cache

L1 is expensive (a `git blame` per changed line of every fix commit) and pure, so its
output is cached under `.vouch_cache/l1/`, keyed on repo, pinned HEAD, subject identity,
`EXTRACTOR_VERSION` and the config fingerprint. This is what makes a labelling round
something you can stop and come back to.

**Bump `EXTRACTOR_VERSION` in `vouch/l1/cache.py` whenever the computation changes** — a
new predicate, a changed blame rule, a different interval. `SCHEMA_VERSION` describes the
output's *shape*; a fix that changes what `ownership_loop` counts leaves the shape
identical and every cached value wrong. Pass `--refresh` to recompute one run.

## The checked-in sample profiles

```bash
python scripts/build_sample_profiles.py     # then re-pin PINNED_SNAPSHOTS
```

Never hand-edit one: the filename is a hash of the file's own bytes. What the samples are
and why there are two is in [`../web/README.md`](../web/README.md); why the script exists
and which sample it cannot yet rebuild is in its own docstring.

## Linting

```bash
ruff check .
```

Config is in `pyproject.toml` (`[tool.ruff]`): rule sets `E, F, I, UP, B`, line length 100,
`E501` ignored (prompts/tests carry long lines).

## Building

```bash
pip install build
python -m build          # -> dist/*.whl and dist/*.tar.gz
```

Provider SDKs are an optional extra (`[providers]`), so they are **not** runtime
dependencies of the wheel.

## Running the hosted flow locally

Two processes and one SQLite file. The web app enqueues, the worker runs the pipeline;
neither talks to the other except through `var/vouch.db`.

```bash
# 1. an OAuth app: https://github.com/settings/developers
#    callback = <NEXT_PUBLIC_SITE_URL>/api/auth/callback
cat > web/.env.local <<'EOF'
GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...
NEXT_PUBLIC_SITE_URL=http://localhost:3000
EOF

cd web && npm install && npm run dev      # terminal 1
vouch worker                              # terminal 2, from the repo root
```

The worker needs a judge, so `ANTHROPIC_API_KEY` must be set or every job finishes `failed`
with "the judge could not produce a grounded verdict". `--once` drains the queue and exits,
which is the shape a cron-style deployment wants.

Environment that both sides read:

| Variable | Default | Notes |
|---|---|---|
| `VOUCH_DB` | `var/vouch.db` | Must resolve to the same file from `web/` and the repo root. |
| `VOUCH_PROFILE_DIR` | `var/profiles` | Generated documents. Never `web/data/profiles`, which is tracked. |
| `VOUCH_GIT_BASE` | `https://github.com/` | Where a validated `owner/repo` is cloned from. The test suite points it at a fixture directory, which is how the hosted path is exercised offline. |

`var/` is gitignored in full: it holds repo addresses, subject email addresses, a GitHub
token and real people's profiles. None of it belongs in a commit.

## CI/CD

GitHub Actions in `.github/workflows/`:

### `ci.yml` — on push / PR to `main`

- **lint** job: `ruff check .`
- **test** job: matrix over Python **3.12** and **3.13**, `pytest -q`. Sets a git committer
  identity so the fixture builder works on runners. Fully offline.

### `release.yml` — on `v*` tags

1. **build** — gates on lint + tests, then `python -m build` (sdist + wheel), uploaded as
   an artifact.
2. **github-release** — attaches the artifacts to a GitHub Release with auto-generated
   notes.
3. **pypi-publish** — trusted publishing via OIDC, **gated**: runs only if the repo
   variable `PYPI_PUBLISH == 'true'` and a `pypi` environment exists. Otherwise skipped, so
   a release never fails for lack of PyPI credentials.

### Cutting a release

```bash
git tag v0.1.0
git push origin v0.1.0
```

> These workflows assume the repo is hosted on GitHub. Push the repo and add a remote
> first; they activate on the next push/tag.

## Where the rest of it is written down

- [`plan.md`](plan.md) — the five-layer architecture, the phase table, and what is still open.
- [`../CLAUDE.md`](../CLAUDE.md) — the invariants, and which version constant to bump when.
- [`../web/README.md`](../web/README.md) — the site, the connect flow and the viewer.
- [`render-leakage.md`](render-leakage.md) — a dated audit of whether the render leaks an
  overall score. Read the addenda: the finding it opens is still open.
