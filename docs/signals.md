# Ownership signals

Ownership asks: **does this person return to fix their own bugs, with tests, over time?**

Every signal is a **pure, deterministic function** of the `RepoSnapshot` (plus on-demand
`git blame`). Each carries the commit SHAs that back it — these are the only things the
judge is allowed to cite. Thresholds live in `vouch/config.py` (see
[Configuration](./configuration.md)).

The extractors are the honest, falsifiable heart of the tool; they are unit-tested against
tiny synthetic repos with both positive and discriminating negative cases.

## The five signals (v0)

| key | value type | weight | intuition |
| --- | --- | --- | --- |
| `returned_to_own_code` | count | 0.30 | came back to the same files after a real gap |
| `fixed_own_bug` | count | 0.30 | fixed code they themselves authored |
| `tests_accompany_fixes` | fraction | 0.25 | fixes that also touched tests |
| `revert_recovery` | count | 0.10 | own code reverted, then re-landed |
| `commit_atomicity` | fraction | 0.05 | focused, single-purpose commits (weak proxy) |

### `returned_to_own_code`

For each file the subject touched, if the span between their first and last touch is at
least `return_gap_days` (default **14**), the file counts as a "return" — sustained
involvement, not a drive-by.

- **Value:** number of files with a sustained return.
- **Evidence:** the first and last SHA for each such file.

### `fixed_own_bug`

For each of the subject's **fix commits** (subject line contains a fix keyword — `fix`,
`bug`, `resolve`, `patch`, `regression`, `hotfix`, `correct`), the changed source lines are
blamed against the parent commit. If any changed line was authored by the subject, it's a
self-fix.

- **Value:** number of self-fix commits.
- **Evidence:** those fix commit SHAs.
- **Requires** `repo_path` (blame). Without it the signal is `0` — an honest degradation,
  never a guess.

> **Honesty note.** The blame step is exact; the "is this a fix?" classification is a
> subject-line keyword *proxy*. It is deliberately conservative — it will miss fixes
> phrased differently rather than invent them.

### `tests_accompany_fixes`

Of the subject's fix commits, the fraction that also add or modify a test file (path under
`tests/`, or matching `test_*` / `*_test` / `conftest.py`).

- **Value:** fraction in `[0, 1]` (`0.0` if there are no fix commits).
- **Evidence:** the fix commits that *did* include tests (the positive receipts).

### `revert_recovery`

An honest proxy for "reverted, then re-landed correctly." A commit is a revert if its body
carries git's `This reverts commit <sha>` marker (parsed at ingest time). If the reverted
commit was authored by the subject and the subject later touches an overlapping file, it
counts as a recovery.

- **Value:** number of such recoveries.
- **Evidence:** `[revert_sha, recovery_sha]` per case.

### `commit_atomicity`

A weak proxy for focus: the fraction of the subject's commits touching at most
`atomic_max_files` (default **3**) files.

- **Value:** fraction in `[0, 1]`.
- **Evidence:** a sample of the focused commit SHAs (capped to keep the bundle small).

## Dropped in v0: `review_followthrough`

The original design included `review_followthrough` (responding to review with follow-up
commits). It is **not derivable from pure git** — it needs GitHub PR/review data. Rather
than fake it, v0 drops it and reserves the key for a later version that may add an optional
GitHub API step to `ingest`.

## The grounding guarantee

`extract` builds a `commit_index` containing a `CommitMeta` for **exactly** the SHAs the
signals cite — no strangers, nothing missing. This is the structural anti-hallucination
guarantee: the judge can only cite what's in the index, and the grounding validator
enforces it.
