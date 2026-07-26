# Data model

All core types are Pydantic v2 models in `vouch/schemas.py`. They define the contracts
between pipeline stages:

```
ingest  -> RepoSnapshot
extract -> EvidenceBundle   (Signals + CommitMeta index)
judge   -> Verdict
report  -> CapabilityReport
```

## `CommitRecord`

One normalized non-merge commit — the unit the extractors reason over.

| Field | Type | Notes |
| --- | --- | --- |
| `sha` | `str` | full commit SHA |
| `author_name` | `str` | |
| `author_email` | `str` | canonical identity key |
| `authored_at` | `datetime` | |
| `subject` | `str` | commit subject line |
| `files` | `list[str]` | touched paths (handles adds/mods/deletes/renames) |
| `test_files` | `list[str]` | subset of `files` that look like tests |
| `reverts_sha` | `str \| None` | if a revert, the SHA it reverts (parsed from body at ingest) |

## `RepoSnapshot`

Deterministic, cacheable normalization of a repo at a pinned HEAD. Cached by
`repo + head_sha`.

| Field | Type |
| --- | --- |
| `repo` | `str` |
| `head_sha` | `str` |
| `commits` | `list[CommitRecord]` |
| `ingested_at` | `datetime` |

## `Signal`

A single computed ownership signal with the SHAs that back it.

| Field | Type | Notes |
| --- | --- | --- |
| `key` | `str` | e.g. `"fixed_own_bug"` |
| `value` | `float \| int \| bool` | |
| `evidence` | `list[str]` | commit SHAs — every one must also be in the bundle's `commit_index` |
| `computed_at` | `datetime` | |

## `CommitMeta`

Human-readable anchor for one SHA the judge may cite. **No diff, ever.**

| Field | Type |
| --- | --- |
| `sha` / `short` | `str` |
| `authored_at` | `datetime` |
| `subject` | `str` |
| `n_files` | `int` |
| `touched_tests` | `bool` |

## `EvidenceBundle`

The exact payload handed to the judge — the deterministic/LLM contract.

| Field | Type | Notes |
| --- | --- | --- |
| `repo` | `str` | |
| `subject` | `str` | canonical author email under evaluation |
| `dimension` | `str` | `"ownership"` |
| `window_first` / `window_last` | `date \| None` | subject's activity window |
| `n_commits_by_subject` | `int` | |
| `signals` | `list[Signal]` | |
| `commit_index` | `dict[str, CommitMeta]` | a `CommitMeta` for **exactly** the cited SHAs |

`known_shas()` returns every SHA the judge is allowed to cite; the grounding validator
uses it.

## `Verdict`

The model's judgment. Must cite only SHAs present in the input bundle.

| Field | Type | Notes |
| --- | --- | --- |
| `dimension` | `str` | `"ownership"` |
| `score` | `float` | `0..1` |
| `confidence` | `float` | `0..1` — calibrated, not vibes |
| `freshness` | `date` | most recent supporting evidence |
| `rationale` | `str` | must reference cited SHAs |
| `cited_evidence` | `list[str]` | the SHAs the model actually used |

## `CapabilityReport`

The final artifact: verdict + evidence + full provenance.

| Field | Type |
| --- | --- |
| `repo` / `subject` / `dimension` | `str` |
| `verdict` | `Verdict` |
| `evidence` | `list[Signal]` |
| `judge_model` | `str` |
| `prompt_version` | `str` |
| `generated_at` | `datetime` |
