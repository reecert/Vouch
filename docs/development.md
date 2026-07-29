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
  classification, evidence strength, scoping. Each fact gets a positive and a
  discriminating negative case. `test_l1_golden.py` pins byte-identical output over eight
  fixture repos; `test_l1_cache.py` covers the persistence cache, including that every
  input which changes the facts also changes the key.
- **`test_l2_*.py`** — the JSONL parser (including mutated and non-session logs), derived
  metrics, and the payload-closure test that walks the *schema* and fails on any free-text
  field.
- **`test_l3_*.py`** — the session↔commit join, its measured precision/recall harness, and
  repo identity.
- **`test_l4_*.py`** — structured-output and grounding retries, the support check and the
  adversarial mock modes, driven by scripted providers (no real LLM).
- **`test_l5_profile.py`** — profile assembly and the frozen snapshot.
- **`test_eval*.py`, `test_labeling.py`** — the eval harness, the corpus and its
  address-free selectors, and the blind labelling procedure (§ *Labelling the corpus*).
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
  load if it finds one.

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

## Project layout

See [docs/plan.md](plan.md) for the five-layer architecture and open questions.
[development.md](development.md) covers setup, labelling, CI/CD, and release.
