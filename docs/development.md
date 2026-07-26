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

- **`tests/test_ingest.py`** — git parsing, caching, revert-body parsing, blame.
- **`tests/test_extract.py`** — every signal, with a positive and a discriminating
  negative case, plus the `commit_index`-only-cites invariant.
- **`tests/test_judge.py`** — structured-output + grounding retries, provider fallback,
  driven by a scripted `StubProvider` (no real LLM).
- **`tests/test_report.py`** — report assembly, JSON round-trip, markdown rendering.
- **`tests/test_cli.py`** — CLI wiring via `typer`'s `CliRunner`; the judge is
  monkeypatched, and `--evidence-only` exercises the deterministic path with no patching.

### Fixtures

`tests/fixtures/builder.py` builds tiny synthetic git repos on the fly with full control
over author identity, dates, touched files, and revert bodies — the exact axes the signals
key off. This exercises real `git` behavior without touching the network.

```python
from tests.fixtures.builder import ALICE, Step, build_repo

shas = build_repo(tmp_path / "r", [
    Step(ALICE, "2024-01-01T10:00:00", "add", {"a.py": "1\n"}),
    Step(ALICE, "2024-02-10T10:00:00", "fix a", {"a.py": "2\n"}),
])
```

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

See the [architecture doc](../ARCHITECTURE.md) for the full module breakdown and the scale
path (which is deliberately *not* built in v0, only left un-foreclosed).
