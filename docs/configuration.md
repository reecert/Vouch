# Configuration

**Config over code.** Signal weights, extractor thresholds, provider order, and the prompt
version live in `vouch/config.py` — not scattered as literals. Every report records the
config + prompt version that produced it, so it is reproducible.

## Signal weights

`SIGNAL_WEIGHTS` — guidance handed to the judge (it is the final arbiter, not a formula):

```python
SIGNAL_WEIGHTS = {
    "returned_to_own_code": 0.30,
    "fixed_own_bug":        0.30,
    "tests_accompany_fixes":0.25,
    "revert_recovery":      0.10,
    "commit_atomicity":     0.05,
}
```

## Thresholds

`THRESHOLDS` (`Thresholds` dataclass) tunes the deterministic extractors:

| Field | Default | Used by |
| --- | --- | --- |
| `return_gap_days` | `14` | `returned_to_own_code` — min span to count a re-touch as sustained |
| `fix_keywords` | `fix, bug, resolve, patch, regression, hotfix, correct` | `fixed_own_bug`, `tests_accompany_fixes` |
| `atomic_max_files` | `3` | `commit_atomicity` — max files for a "focused" commit |
| `revert_marker` | `"This reverts commit"` | revert detection at ingest |

## Provider chain

`PROVIDER_CHAIN` — ordered `ProviderSpec`s (name, model, API-key env var):

```python
PROVIDER_CHAIN = (
    ProviderSpec("gemini", "gemini-2.0-flash",        "GEMINI_API_KEY"),
    ProviderSpec("groq",   "llama-3.3-70b-versatile", "GROQ_API_KEY"),
    ProviderSpec("ollama", "qwen2.5-coder",           None),
)
```

## Prompt + retries

| Constant | Default | Meaning |
| --- | --- | --- |
| `PROMPT_VERSION` | `"ownership-v0"` | stamped into the prompt and every report |
| `MAX_STRUCTURED_RETRIES` | `1` | bounded retry on JSON/schema parse failure |
| `MAX_GROUNDING_RETRIES` | `1` | bounded retry on ungrounded SHA citation |

## The `Config` object

`CONFIG` bundles all of the above into one fingerprintable object, passed through the
pipeline. Override it by constructing a `Config(...)` and passing it to `extract`,
`judge`, etc.
