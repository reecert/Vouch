# Getting started

## Requirements

- Python **≥ 3.12**
- `git` on your `PATH`

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"            # core + test tooling (pytest, ruff)
```

Provider SDKs are **optional** — they are lazy-imported behind the judge adapter, so the
deterministic core (ingest/extract) and the entire test suite need none of them. Install
them only when you want to run the LLM judge:

```bash
pip install -e ".[providers]"      # google-genai, groq, ollama
```

## Your first run — no LLM required

The `--evidence-only` flag runs the fully deterministic pipeline and prints the
`EvidenceBundle` the judge *would* receive. It needs no API key and no network beyond the
initial clone:

```bash
vouch run https://github.com/pallets/itsdangerous.git \
  --author <author-email> \
  --evidence-only
```

You'll see the five ownership signals, each with the commit SHAs that back it, plus a
`commit_index` containing exactly those SHAs.

A local path works anywhere a URL does:

```bash
vouch run ./path/to/local/repo --author dev@example.com --evidence-only
```

## Running the full report

The full report calls the LLM judge, which needs at least one provider configured:

```bash
export GEMINI_API_KEY=...          # Google AI Studio free tier
vouch run <repo_url> --author <email>
```

If no provider is available, the command fails loud with guidance:

```
judge failed: no judge provider available (set GEMINI_API_KEY / GROQ_API_KEY, or run Ollama)
(re-run with --evidence-only to inspect the deterministic signals)
```

See [The judge](./judge.md) for the full provider chain and fallback behavior.

## Caching

`ingest` caches into `.vouch_cache/` by `repo + HEAD SHA`. The first run clones (blobless)
and parses; subsequent runs re-parse nothing. Only the initial clone touches the network.
