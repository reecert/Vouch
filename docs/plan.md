# Rebuild plan

Status: **live document.** Phases 1a–1c and 1e done; 1d built but uncalibrated.
See Part 4 for the phase table and Part 5 for what is still open.

Companion doc: [`baseline-competitor.md`](./baseline-competitor.md) (competitor quality baseline).

---

## Part 1 — What the existing prototype gives us

The prototype is `vouch/` (~1,300 LOC of source, ~800 LOC of tests, 57 tests, all passing, all
offline). It is a genuinely well-built v0 of a *narrower* product. The audit below is what carries
forward, what is quietly wrong, and what should be deleted.

### 1.1 Reusable — keep, mostly as-is

| Component | Why it survives |
|---|---|
| `ingest/` git plumbing | `_FS`/`_RS` separator parsing, `--name-status` walk, HEAD-pinned snapshot cache, `changed_old_lines` hunk parsing. Correct and fast. |
| Blame primitive | `blame_line_author` is the right primitive for "who wrote the line being fixed". Needs a perf fix (§1.2) but the approach is sound. |
| Robustness contracts in `judge/` | Structured-output retry, **evidence-grounding validator**, provider fail-forward. The grounding validator (`validate_grounding`, incl. short-SHA prefix matching) is the single most valuable piece of code in the repo and transfers to L4 unchanged. |
| `judge/cache.py` | Content-hash caching that deliberately ignores volatile `computed_at`. Exactly right; the L4 judge needs the same, keyed on diff content. |
| `eval/` harness | Train/holdout split, refusal to report an empty holdout, `<15 labels` warning, `calibration_status: insufficient_n`, and the **support check** (`check_support`) that rejects grounded-but-inflated verdicts. This is the discipline the brief's quality bar asks for, already built. |
| `eval/mock.py` adversarial modes | Malformed JSON / hallucinated SHA / inflated score adversaries. Keep and extend with an "over-eager verdict on thin evidence" adversary for the `insufficient_evidence` enum. |
| `tests/fixtures/builder.py` | Synthetic-repo builder with full control of author identity, dates, paths, revert bodies. This is the foundation for the confound fixtures the brief requires — extend, don't replace. |
| CI + `pyproject.toml` | Ruff + pytest on 3.12/3.13, offline suite, lazy provider imports. Fine as-is. |

### 1.2 Confounded — carries forward only after being fixed

These are real defects, not style notes.

**a. No confound detection exists at all.** The brief's L1 requires detecting squash-merge
histories, solo repos, bot/vendored/generated/lockfile noise, and rebase-rewritten authorship.
The prototype detects none of them, and every one of them distorts the signals it does compute:

- Squash-merge collapses a PR into one commit authored by the merger → `fixed_own_bug` blames to
  the wrong person, `commit_atomicity` reads a squashed PR as unfocused.
- Solo repo makes ownership trivially 100% — there is no one else to have written the bug.
- `files` includes `package-lock.json`, `dist/`, `vendor/` unfiltered → `commit_atomicity` is
  noise-dominated and `returned_to_own_code` counts lockfile churn as sustained involvement.

**b. `signal_fixed_own_bug` is O(lines changed) subprocesses.** It runs one `git blame` per changed
line, per file, per fix commit (`extract/__init__.py:88-92`). A 50-line fix across 3 files is up to
150 blame invocations. Fix: `git blame` accepts multiple `-L` ranges — one porcelain call per
(commit, file) parsed once. This is the difference between "works on a fixture" and "works on a
real repo".

**c. Identity is a single exact-match email.** `_subject_commits` filters `author_email == subject`
(`extract/__init__.py:28`). Real engineers commit under several addresses (work, personal, GitHub
`users.noreply`). Everything under the other addresses is silently invisible, which reads as low
ownership. Fix: parse with mailmap-resolved `%aE`/`%aN` and accept an explicit alias set; treat
unresolved multi-identity as its own confound flag.

**d. Signal semantics are weaker than their names.** `returned_to_own_code` counts *any* file whose
first and last touch are ≥14 days apart — it does not check the return was corrective, so a
long-lived repo satisfies it by existing. `revert_recovery` counts "a later commit touching an
overlapping file" as a recovery, which in an active repo is near-guaranteed. Both need a tighter
predicate before a report is allowed to say "returns to fix own bugs".

**e. No minimum-n floor.** `tests_accompany_fixes` returns `1.0` from a single fix commit. A report
that prints "100%" off n=1 is exactly the flattering-conclusion failure the quality bar forbids.
Every ratio needs a denominator floor below which it is suppressed, not rounded.

**f. Output is not byte-reproducible.** Every `Signal` carries `computed_at=datetime.now()`, so no
two extractor runs are byte-identical and golden-file tests are impossible as written. (The judge
cache already works around this by hashing around the field.) Fix: timestamps live in a
non-hashed envelope, never inside the fact payload.

**g. `is_test_path` over-matches.** `(^|/)(tests?|test_)` matches `testing/anything.py` as a test
file. Minor, but it corrupts a golden file.

**h. Free-tier provider chain is a policy problem for a product.** Gemini AI Studio's free tier may
train on submitted data. `ARCHITECTURE.md` argues this is acceptable because inputs are public-repo
metadata. Under the new brief that argument breaks: L2 uploads derived behavioural metrics about a
named individual, and L4 sends real diffs. Neither should go to a train-on-input tier.

### 1.3 Dead — delete

- `Thresholds.revert_marker` (`config.py:47`) — defined, never read; `ingest` uses its own `_REVERT_RE`.
- `_ = PROVIDER_CHAIN` (`judge/__init__.py:316`) — vestigial import-keeper.
- `SIGNAL_WEIGHTS` — a weighted-score scaffold whose only consumers are the prompt and the mock.
  The new brief forbids an overall single score, so the weights have no destination. Delete them
  rather than let a hidden scalar leak back in.
- `Signal.value: float | int | bool` — the `bool` arm is never produced.
- `EvidenceBundle.dimension = "ownership"` as a hardcoded default, and the whole single-dimension
  assumption threaded through `extract`, `prompt`, `report`, `eval`.
- `report/to_markdown` — replaced by L5.
- `eval/labels.yaml` is **empty** (`train: []`, `holdout: []`). The eval harness — described in
  `ARCHITECTURE.md` as "the crux" — has therefore never been run against real data. The machinery
  is real; the calibration evidence does not exist yet. Treat every quality claim about the current
  judge as unmeasured.
- `docs/*.md` (7 files) describe the v0 shape and will be stale on contact. Rewrite alongside code.

### 1.4 The one contradiction to resolve first

`ARCHITECTURE.md` states as a hard non-goal: *"No raw diffs sent to the model. Ever."* The whole
anti-hallucination story is built on it — the judge sees pre-computed metadata and cannot cite what
it was never handed.

**The new brief's L4 requires the opposite:** "Reads actual diffs. Answers: was this a real fix or
cosmetic, does the added test exercise the failure, did scope creep."

This is not a tweak. It means:

- `judge/prompt.py` and the metadata-only `EvidenceBundle`-as-prompt-payload are **dead**.
- The anti-hallucination guarantee must be rebuilt on a different footing: the model may now read
  diff content, but it may only *cite* SHAs and file paths that L1 handed it, and every claim must
  carry a locator that a validator can check against the real tree. The grounding validator
  survives and gets stricter (SHA **and** path, not just SHA).
- The privacy story changes shape. Diffs from a public repo are already public, so phase 1 is safe;
  private-repo support (explicitly a non-goal) would need this revisited before it ships.

I flag this rather than silently reversing a documented invariant. §2.4 assumes the reversal.

---

## Part 2 — Architecture

Five layers, strictly separated. Each layer's output is a serialisable artifact with a schema
version; each layer is independently testable; no layer reaches backwards.

```
             ┌─ user's machine ────────────────┐
             │  ~/.claude/projects/*.jsonl     │
             │            │                    │
             │            ▼                    │
             │  L2  session telemetry CLI      │
             │            │                    │
  public     │            ▼                    │
  repo ──► L1 extractor ──┴──► L3 join         │   ← runs LOCALLY (see §2.3)
             │                 │               │
             └─────────────────┼───────────────┘
                               │  upload: derived metrics + corroboration records only
                               ▼
                   L4 diff judge ──► L5 profile + share link
```

### 2.1 L1 — deterministic extractor

Pure Python, no LLM, no network beyond the clone. Arithmetic only. **Byte-reproducible:** same repo
+ same HEAD + same config ⇒ byte-identical output, enforced by golden-file tests.

Two outputs, deliberately separated:

1. **`RepoFacts`** — the measurements.
2. **`ConfoundReport`** — what would make those measurements wrong.

Measurements (each carries backing SHAs and its own denominator):

| fact | definition sketch |
|---|---|
| `ownership_loop` | subject fixes a defect in code that blames back to the subject, with a test in the same or an adjacent commit. Tightened from the prototype's `fixed_own_bug` + `tests_accompany_fixes`. |
| `revert_rate` | subject's commits later reverted ÷ subject's commits |
| `test_accompanies_fix` | fix commits touching a test ÷ fix commits |
| `followup_latency` | distribution of (defect-introducing commit → fixing commit) over subject-authored pairs |
| `commit_scoping` | file/hunk-count distribution after noise filtering |

Confound flags — each with severity, the numbers behind it, the facts it invalidates, and the
**direction** of the distortion (a flag that says only "squash-merged" is useless; it must say
"ownership is understated because authorship collapses to the merger"):

`squash_merge_history`, `solo_repo`, `bot_dominated`, `vendored_or_generated_bulk`,
`rebase_rewritten_authorship`, `shallow_history`, `unresolved_identity_aliases`, `short_window`,
`low_denominator`.

**Rule: a confound flag can suppress a fact.** If `solo_repo` fires, `ownership_loop` does not emit
a value — it emits `not_assessable`. Suppression happens in L1, deterministically, before any model
sees anything. This is the structural version of "never produce a flattering conclusion from weak
data".

### 2.2 L2 — session telemetry CLI

Runs on the user's machine. Parses `~/.claude/projects/**/*.jsonl`.

Derived metrics: plan-mode-before-execute rate, test-or-build-run-after-edit rate,
revision-before-acceptance, prompts per session, redirect/interrupt frequency, tool and MCP usage.

Hard constraints, implemented as code not policy:

- **Raw logs and source never leave the machine.** The upload payload is constructed as an explicit
  allow-listed struct; there is no path by which a log line or file content reaches it. Enforced by
  a test that asserts the payload schema is closed and contains no free-text field.
- **Print exactly what will be uploaded, require confirmation.** The confirmation renders the actual
  serialised payload — not a summary of it.
- **Versioned parser, fail soft.** The Claude Code log format is unstable and undocumented. The
  parser declares which format versions it understands; on an unrecognised shape it degrades to
  git-only mode with a stated coverage gap, and never guesses. Unparsed-record count is itself a
  reported metric — silent partial parsing is the failure mode that would quietly corrupt L3.
- **Minimum-n floors.** Below the floor a rate is suppressed, not rounded. (Our first concrete
  improvement over the baseline, which publishes five percentages off `Sessions: 18`.)

### 2.3 L3 — correlation. The differentiator.

Joins sessions to commits by timestamp window + file-path overlap.

**Decision: the join runs locally, inside the L2 CLI.** Rationale: file-path overlap needs both
sides. Uploading session file paths would mean paths from *every* project in the user's log
directory — including private and client work unrelated to the connected repo — crossing the
network. Running the join locally means only the outcome (commit SHA + corroboration verdict +
match quality) is uploaded. Nothing about unmatched sessions leaves at all.

*Tradeoff, stated:* the join algorithm ships to the client, so improving it requires users to re-run
the CLI, and we cannot re-derive corroboration server-side from stored data. Accepted because the
CLI is cheap to re-run and the privacy property is the product. The alternative — salted path
hashes so the server can match against the public repo's known paths without learning unknown ones —
is workable and is listed as an open question (§4).

**Match scoring.** For each (session, commit) candidate pair:

- *Temporal:* session activity precedes the commit within a window; direction is a hard constraint
  (edits before commit), magnitude is a decaying score.
- *Path overlap:* Jaccard / containment between session-edited paths and commit paths.
- *Corroboration verdict:* `corroborated` | `ambiguous` | `uncorroborated`, with the score and the
  contributing evidence attached. Never a bare boolean.

**Failure modes to handle explicitly, because they decide accuracy:**
clock skew and timezone between log and commit; `--amend` and rebase moving commit timestamps after
the session; squash-merge mapping many session edits onto one commit; one session spanning many
commits and one commit spanning many sessions (many-to-many is the normal case, not the edge);
sessions that edited files but produced no commit; commits made outside any session (the honest
majority for most people).

**Accuracy is measured, not asserted.** L3 gets its own labelled set — sessions and commits where
the true correspondence is known by construction — and reports precision/recall on the match with
its n, under the same honest-at-small-n discipline the existing eval harness already enforces.
Uncorroborated is a first-class, expected outcome: most commits will have no session evidence, and
the report must say so rather than implying absence of evidence is evidence of absence.

### 2.4 L4 — LLM judgment, diff-level

Reads actual diffs (public repos only in phase 1). Answers per-commit questions the metadata cannot:
was this a real fix or cosmetic; does the added test exercise the failure it claims to; did scope
creep.

- **`insufficient_evidence` is an enum member in a strict output schema, not a prompt instruction.**
  Implemented with the Anthropic API's structured outputs (`output_config.format` /
  `messages.parse()` with a strict JSON schema), so the model is *constrained* to the verdict
  vocabulary and can always express "not enough here". A verdict outside the enum is unrepresentable
  rather than merely discouraged.
- **Every claim carries a locator:** SHA + file path (+ hunk where applicable). The grounding
  validator — ported from the prototype and extended from SHA-only to SHA+path — rejects any claim
  whose locator does not exist in the input. Reject → one bounded retry → fail loud. Unchanged
  policy from the prototype, which got this right.
- **The support check survives.** `check_support`'s rule — a strong verdict must rest on cited
  receipts and non-zero facts — is re-expressed against the new verdict enum and remains outside the
  model, in the harness that holds both the verdict and the evidence.
- **Recommended model: `claude-opus-5`** as the primary judge, keeping the `JudgeProvider` protocol
  so the chain stays swappable. Rationale: diff-level judgment is the quality-critical seam, this is
  a product rather than a free-tier prototype, and structured outputs + prompt caching (stable
  system prompt across many per-commit calls) make the per-commit cost tractable. See §4 for the
  cost question.

### 2.5 L5 — report + web app

Next.js, TypeScript, Tailwind. Shareable read-only link, no login to view.

Report structure (informed by the baseline, §2 of `baseline-competitor.md`):

1. **Evidence inspected** — repos, commit window, session coverage, what was excluded and why. Up front.
2. **Dimensional readouts** — qualitative bands, per dimension, each with its evidence and its own
   confidence. **No overall single score, no rank.**
3. **Risks to probe** — standing section: what to ask in the interview. Promoted to this position
   because the reader is a screener (§5, Q1); generating the next question is the job.
4. **Corroboration** — which claims have session evidence behind them and which do not.
5. **Limitations** — standing section: what this profile cannot see.

Share links resolve to **frozen snapshots**, not live profiles (adopted from the baseline's
"frozen profile projections" — a good idea, and the right default for a document about a person).

---

## Part 3 — Schema sketch

Shapes, not final field lists. Every artifact carries `schema_version` and a content hash; volatile
timestamps live in an envelope, never inside the hashed payload (§1.2f).

```python
# ---- L1 ---------------------------------------------------------------
class Locator(BaseModel):          # the atom of citability
    sha: str
    path: str | None = None
    hunk: tuple[int, int] | None = None

class Fact(BaseModel):
    key: str
    value: float | int | None      # None == not_assessable
    numerator: int | None          # denominators are always visible
    denominator: int | None
    status: FactStatus             # measured | suppressed_low_n | not_assessable
    evidence: list[Locator]

class Confound(BaseModel):
    key: ConfoundKey               # enum
    severity: Severity             # info | warn | invalidating
    detail: str                    # numbers, not adjectives
    invalidates: list[str]         # fact keys
    direction: BiasDirection       # overstates | understates | unknown

class RepoFacts(BaseModel):
    repo: str; head_sha: str
    subject: Identity              # canonical + resolved aliases
    window: tuple[date, date]
    facts: list[Fact]
    confounds: list[Confound]
    excluded_paths_summary: dict[str, int]   # bot/vendored/generated/lockfile counts

# ---- L2 (the upload payload — closed, allow-listed, no free text) -----
class SessionMetrics(BaseModel):
    parser_version: str
    log_format_version: str
    n_sessions: int
    n_records_unparsed: int        # silent partial parsing is the enemy
    rates: dict[MetricKey, Rate]   # Rate carries numerator/denominator/suppressed

# ---- L3 ---------------------------------------------------------------
class Corroboration(BaseModel):
    sha: str
    verdict: CorroborationVerdict  # corroborated | ambiguous | uncorroborated
    match_score: float
    basis: MatchBasis              # temporal delta, path overlap, session id (opaque)

# ---- L4 ---------------------------------------------------------------
class Verdict(str, Enum):
    strong = "strong"
    moderate = "moderate"
    limited = "limited"
    insufficient_evidence = "insufficient_evidence"   # first-class, frequent
    not_assessed = "not_assessed"                     # we didn't look — distinct from the above
    contradicted = "contradicted"                     # evidence points the other way

class Claim(BaseModel):
    text: str
    locators: list[Locator]        # validated against L1's known set
    corroborated: bool

class DimensionFinding(BaseModel):
    dimension: str
    verdict: Verdict
    confidence: Confidence         # high | moderate | low — banded, never a bare float
    claims: list[Claim]
    limitations: list[str]
    risks_to_probe: list[str]

# ---- L5 ---------------------------------------------------------------
class Profile(BaseModel):
    subject: Identity
    evidence_inspected: EvidenceSummary
    findings: list[DimensionFinding]   # no aggregate score field, by construction
    confounds: list[Confound]
    limitations: list[str]
    risks_to_probe: list[str]
    provenance: Provenance             # model, prompt version, config hash, generated_at
```

Note `Profile` has no aggregate-score field at all. "No overall single score" is enforced by the
type, not by remembering not to add one.

---

## Part 4 — Phases

**Phase boundary rule:** each phase ends with something runnable and tested. No phase depends on a
later phase's output existing.

| Phase | Scope | Done means |
|---|---|---|
| **0** | This document + baseline. | ✅ **Done.** |
| **1a** | **L1 rebuild.** New schema, confound detection, noise filtering, identity/mailmap resolution, blame perf fix, min-n floors, byte-reproducible output. | ✅ **Done.** 83 new tests; golden files over eight fixture repos (healthy, solo, squash-merged, bot-heavy, lockfile-noisy, rebased, aliased, short-window), each deforming one axis. Goldens pin real SHAs. No LLM in the loop. |
| **1b** | **L2 CLI.** Versioned JSONL parser, derived metrics, upload-preview + confirmation, fail-soft to git-only. | ✅ **Done.** 34 tests. Payload-closure test walks the *schema* (not a sample) and fails on any free-text field; parser degrades cleanly on missing, mutated and non-session logs. Validated against 17,236 real records. |
| **1c** | **L3 join.** Local join, match scoring, three-valued corroboration verdict, labelled join set + precision/recall harness. | ✅ **Done.** 21 tests. Correct on all 10 labelled cases (ground truth known by construction); harness nonetheless reports `insufficient_n` at n=10. Many-to-many, no-match, wrong-project, clock-skew and both sides of the overlap floor covered. |
| **1d** | **L4 judge.** Diff-level prompts, strict output schema with the verdict enum, SHA+path grounding validator, support check, judge cache, eval labels populated. | ⚠️ **Built, not calibrated.** 33 tests; harness ported to dimension verdicts and the v0 pipeline deleted. `insufficient_evidence` observed firing on a genuinely thin history; grounding, support check and the over-eager adversary all pass. **The holdout is still empty** — §5 q8. Treat L4's calibration as unmeasured. |
| **1e** | **L5 web app.** Next.js report, frozen share snapshot, Limitations + Risks-to-probe sections. | ✅ **Done.** 19 tests. A repo goes end-to-end to a frozen `/p/<id>` snapshot; `next build` statically exports it and the HTML carries every required section. Limitations are derived from confounds/sampling/absent layers rather than volunteered by the model. |

**Explicit non-goals for phase 1**, per the brief — not built, not stubbed, not designed around:
employer workspaces, job postings, candidate directory, any two-sided marketplace mechanic, auth
beyond profile ownership, private-repo OAuth, payments.

**Housekeeping:** the repo currently has **zero commits** (branch `master`, everything untracked),
while CI triggers on `main`. First commit of phase 1a should resolve the branch name and land the
existing prototype as its own commit so the rebuild diff is readable.

---

## Part 5 — Open questions

Resolved:

1. ~~**`[MARKET]` was left as a literal placeholder in the brief.**~~ **Hiring teams screening
   candidates.** Founders and engineering leaders are the reader; the subject is someone they are
   evaluating. Consequences, folded into the plan above:

   - **This is the competitor's exact positioning**, so §8 of the baseline is a competitive spec, not a
     reference. The differentiators there (shown-not-asserted corroboration, confound disclosure,
     min-n discipline, diff-level claims) are the product, not nice-to-haves.
   - **"Risks to probe" is elevated from a standing section to a primary one** — a screener's job is
     to decide what to ask in the interview, so the section that generates questions is worth more
     than the section that answers them. Report order in §2.5 should put it directly after the
     dimensional readouts, not last.
   - **`insufficient_evidence` gets *more* load-bearing, not less.** A screener acting on a
     flattering false positive wastes an interview loop; one acting on a stated gap asks a question.
     The band has to be frequent and unembarrassing.
   - **The subject is not the reader**, but consent still governs: phase 1 stays subject-initiated
     (the engineer connects the repo and generates the profile), because the alternative — profiling
     someone from their public commits without involvement — is a different and worse product.
     Recording that as a phase-1 constraint.
   - Phase-1 non-goals are unchanged: this decision does **not** license job postings, employer
     workspaces, or a candidate directory.

Decide before the phase that needs it:

2. ~~**Dimension set (before 1d).**~~ **Four, each backed by facts we
   actually compute.** Deliberately narrower than the competitor's nine; the Limitations section
   carries that, and every dimension can point at a denominator.

   | Dimension | L1 facts | L2 metrics |
   |---|---|---|
   | Ownership | `ownership_loop`, `followup_latency`, `revert_rate` | — |
   | Verification discipline | `test_accompanies_fix` | `test_or_build_after_edit` |
   | Planning discipline | — | `plan_before_execute` |
   | Scope control | `commit_scoping` | `edit_revision` |

   Verification discipline is the one that spans both layers, so it is where corroboration is
   visible to a reader — the same behaviour observed in the commit trail *and* in the session
   trail. That makes it the dimension that best demonstrates the differentiator, and it should
   lead the report. Planning discipline rests on L2 alone, so it is `not_assessed` whenever the
   CLI was not run — stated per-dimension, following the competitor's good habit of scoping
   coverage claims per section rather than in one global disclaimer.

3. ~~**L3 join location (before 1c).**~~ **Local join.** The L2 payload is
   built on it — file paths and shell commands are parsed and retained in memory for L3 to join
   against locally, and are structurally unable to reach the upload. Accepted cost: improving the
   join algorithm requires users to re-run the CLI, and corroboration cannot be re-derived
   server-side from stored data.

4. ~~**Judge cost model (before 1d).**~~ **Bounded deterministic sample.**
   L1 selects a fixed-size commit sample by an auditable rule — every self-fix commit (the
   evidence `ownership_loop` already rests on), plus a seeded sample of the remainder. Cost per
   profile is flat regardless of history length, and the selection is reproducible from the config
   fingerprint. The sampling rule is named in the Limitations section: a reader is told the
   profile read *N of M* commits and how those N were chosen.

5. ~~**Provider policy (before 1d).**~~ **`claude-opus-5` primary**, with the
   `JudgeProvider` protocol retained so the chain stays swappable. The free-tier chain
   (Gemini/Groq/Ollama) is demoted to local development only — per §1.2h, sending real diffs and
   derived behavioural metrics about a named individual to a train-on-input tier is not
   defensible in a product. The eval harness continues to run offline against the mock provider,
   so CI never spends money.

Lower stakes, flagged now so they do not surprise later:

6. **Log-format instability (1b).** `~/.claude/projects/*.jsonl` is an internal, undocumented,
   unversioned format. Every metric in L2 is derived from a shape we do not control and that can
   change without notice. The plan treats this with a versioned parser and fail-soft degradation,
   but the honest framing is that **L2 coverage may silently drop to zero on any Claude Code
   update**, and the product has to keep working (git-only) when it does. Flagging as the single
   largest technical risk in the brief.

7. ~~**Signal semantics (1a).**~~ **Resolved in build: tighter predicate taken.** A "return" now
   requires the fix to land at least `return_gap_days` (14) after the code it repairs, so
   same-session work no longer counts as ownership. Two further calls made while building, both
   in the same direction — under-detect rather than mislabel:

   - **Squash detection rests only on GitHub's `(#123)` subject convention.** A "zero merge
     commits across a long history" arm was implemented, fired on a plain linear fixture, and was
     removed: it cannot distinguish a squash-merged repo from a small project with no PRs, and a
     false squash flag tells a reader to discount numbers that are fine. Cost: a squash-merged
     repo whose team writes its own subject lines goes undetected.
   - **Noise share is measured over human commits only**, so a dependency bot's lockfile churn is
     reported once (as `bot_dominated`) rather than twice.

7. **One brief metric could not be built as named (1b) — flagged rather than faked.** The brief
    asks for *revision-before-acceptance*. Measuring it properly needs accept/reject telemetry,
    and the logs carry only `toolDenialKind` — **2 occurrences across 17,187 records**. That is
    not a denominator. Rather than dress a different measurement in the requested name, L2 ships
    `edit_revision` (share of files edited more than once in a session — the assistant revised
    its own work before moving on) and `human_redirect` (share of sessions containing an
    interrupt or a denial, which is the brief's "redirect/interrupt frequency"). If true
    acceptance telemetry matters, it needs a source other than these logs.

    Related, from the same pass: `plan_before_execute` measures **1/34** on this machine's real
    history. The number is honest — plan mode genuinely is rare here — but a single developer's
    logs are not a calibration set, and it is a reminder that these rates will read low for most
    people until there is a population to compare against.

8. **L4 is built but uncalibrated. The harness is now ready; the labels are not.** Half of this
    is closed and half is not, so stating both:

    - ✅ **The harness is ported.** `vouch/eval/` now scores per-dimension enum verdicts, and
      reports **overclaims separately from underclaims** — concluding where a human declined is
      the failure the quality bar exists to prevent, and an aggregate agreement figure hides it.
      The v0 disciplines survive intact.
    - ✅ **The v0 pipeline is deleted.** Its 57 tests were passing against code that no longer
      ships, which made the suite look like better coverage of L4 than it was.
    - ❌ **`eval/labels.yaml` is still empty**, exactly as it was in the prototype (§1.3). Every
      guard rail *around* the judge is tested — grounding, the support check, the over-eager
      adversary, `insufficient_evidence` firing on a thin history. Whether the judge's verdicts
      *agree with human judgement* remains unmeasured, and nothing here licenses a claim about
      it. A test asserts the file is empty, so it fails the day someone populates it — which is
      exactly the moment the accuracy claims need revisiting.

    What remains is a **data task, not a code task**: real repos, hand-labelled per dimension,
    split train/holdout. Two properties matter more than volume — the corpus must contain
    labels that are legitimately `insufficient_evidence` (a corpus of only conclusive labels
    teaches nothing about overclaiming), and the holdout must be labelled before the prompt is
    iterated against train. ~20 rows would move `calibration_status` off `insufficient_n`;
    fewer would still surface an overclaim rate, which is the number worth having first.

    ✅ **The instrument for that data task now exists** — `vouch label`, and the corpus it
    reads. The properties above are enforced by the tool rather than left to the labeller:

    - **Blind by construction.** `build_task` takes L1 and L3 and has no parameter an L4
      finding could arrive through, so "just show the labeller what the model said" is not
      reachable. Shown a verdict first, a human agrees with it far more often than they
      otherwise would, and the eval would then measure how persuasive the judge is.
    - **The split is a hash of `(corpus_id, dimension)`**, fixed before the evidence is
      rendered and not re-rollable. Per pair rather than per repo, so no history lands
      wholly on one side.
    - **Evidence is rendered as intervals.** A `0/5` is shown as the range it is, so the
      person writing the ground truth cannot read it as a zero either.
    - **No address is written down.** A label is keyed on a corpus id; `eval/repos.yaml`
      stores a selector (rank + digest) and resolves it against the clone at run time.
      `load_labels` scans the raw file for anything email-shaped and refuses to load.
      Populated label sets are gitignored — they are one person's judgements about named
      engineers who did not ask to be judged.
    - **L1 output is cached** on (repo, pinned HEAD, identity, extractor version, config
      fingerprint), which is what makes a labelling round something a human can stop and
      come back to rather than a forty-seven-minute sitting done once under time pressure.

    So the remaining gap is narrower than it was, and unchanged in kind: **rows in the
    file.** Nothing here licenses a claim about the judge's accuracy.

9. **L3 accuracy is real but narrow (1c).** The join is correct on all ten labelled cases and
    the harness still refuses to call that evidence. What the number honestly supports: *the
    scorer behaves correctly on histories we constructed*. What it does not support: that it
    generalises to real repos, where commit timestamps move under rebase, several people edit the
    same files in the same hour, and sessions are abandoned without committing. Getting past
    `insufficient_n` needs ≥20 labelled commits from histories we did **not** build — the
    cheapest source is this repo's own history plus its session logs, which is a real labelling
    task, not a code change. Until then the profile should present corroboration coverage as a
    count, never as an accuracy claim.

10. **L2 log parsing is verifiable, not synthesized (1b).** This machine has
   54 session JSONL files across 3 projects, carrying `mode`, `permission-mode`, `user`,
   `assistant`, `attachment`, `system`, `file-history-snapshot`, `file-history-delta`,
   `last-prompt` and `queue-operation` records. `mode`/`permission-mode` are what
   plan-mode-before-execute reads. So 1b can be built and tested against real logs rather than an
   invented shape — which does **not** soften risk 6 above: one local sample is not a format
   guarantee, and the versioned-parser/fail-soft design stands.

11. ~~**Naming.**~~ The repository was renamed `Aiapp` -> `vouch`.
