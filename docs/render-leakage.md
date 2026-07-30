# Render leakage audit — does the viewer leak an overall score?

**Question.** The competitor's sample profile leads with a field labelled "Overall signal"
while its footer claims no black-box score (`docs/baseline-competitor.md`). Does our own
render have the same leak?

**Scope.** Read-only. Nothing was changed. This documents what is, not what to do about it.

**What was read.** `vouch/l5/profile.py`, `vouch/l5/ordering.py`, `vouch/l5/limitations.py`,
`vouch/l4/schema.py`, `vouch/l4/dimensions.py`, `vouch/l1/config.py`, `vouch/l1/extract.py`,
`vouch/l3/join.py`, `web/lib/profile.ts`, `web/lib/data.ts`, `web/components/Profile.tsx`,
`web/app/layout.tsx`, `web/app/p/[id]/page.tsx`, `web/app/page.tsx`.

**How the geometry was measured.** The committed static export (`web/out/`, built 2026-07-28
21:08) served over HTTP and loaded in headless Chrome; every leaf text node's
`getBoundingClientRect()` recorded in DOM order. Mobile was measured inside a 390×844 iframe
because Chrome on macOS clamps its window width to ~500px — a direct `--window-size=390`
screenshot renders a 500px layout cropped to 390 and shows false clipping. All mobile
numbers below come from a true 390px layout viewport.

**Fixtures.** Both checked-in snapshots: `c873f3c18cfc7dc8` (with telemetry, no confounds)
and `5c7e853845a45899` (git-only solo, one invalidating confound). Both are synthetic.

---

## 1. The render path

```
RepoFacts + JudgeResult + SessionMetrics + CorroborationReport
  └─ build_profile()            vouch/l5/profile.py:134
       ├─ order_findings()      vouch/l5/ordering.py:106   ← decides what is first
       ├─ derive_limitations()  vouch/l5/limitations.py:37
       └─ compute_id()          vouch/l5/profile.py:126
  └─ JSON in web/data/profiles/<id>.json
       └─ loadProfile()         web/lib/data.ts:25
            └─ ProfileView      web/components/Profile.tsx:141   ← all labels live here
```

The viewer computes nothing. It has no arithmetic on profile values anywhere — no reduce, no
average, no sort. `web/lib/profile.ts` mirrors the Python types and adds only label maps and
`shortSha`. The claim in `web/README.md:29` ("It computes nothing") holds as written.

**So there is no `Profile` field, and no derived render value, that is an aggregate score.**
The direct form of the competitor's leak is absent. What follows is the indirect form.

---

## 2. What a screener sees in the first viewport, in DOM order

`y` is the top edge in CSS pixels from the document top. Rendered with
`c873f3c18cfc7dc8`; the solo fixture differs only in that its intro paragraph is one line
shorter, shifting everything up ~23px, and its fourth card reads `Not collected`.

### Desktop — 1440px wide

Measured viewport height 813px (a 900px Chrome window less browser UI). Marked ▸ are the
items that clear a full 900px viewport instead.

| y | element | text |
|---|---|---|
| 56 | `p` eyebrow | ENGINEERING CAPABILITY PROFILE |
| 80 | `h1` | **alice@example.com** |
| 124 | `p` | Built from a git history and consented local session telemetry. It describes observable behaviour and states what it cannot see. It supports a hiring decision; it does not make one. |
| 233 | `h2` | EVIDENCE INSPECTED |
| 253 | `p` | Stated before anything is concluded from it. |
| 293/311 | `dt`/`dd` | Repository · example/with-telemetry |
| 293/311 | `dt`/`dd` | Commits by subject · **12 of 14** |
| 293/311 | `dt`/`dd` | Diffs read · **14 of 14** |
| 293/311 | `dt`/`dd` | Active window · 2024-01-01 → 2024-02-20 |
| 367/385 | `dt`/`dd` | Measurements · **5 measured, 0 withheld** |
| 367/385 | `dt`/`dd` | Sessions · **20** |
| 367/385 | `dt`/`dd` | Head · 753b3cef |
| 367/385 | `dt`/`dd` | Excluded files · 1 docs, 1 lockfile |
| 486 | `h2` | DIMENSIONS |
| 506 | `p` | Reported side by side. There is no overall score. |
| 567 | `h3` | Verification discipline |
| 569 | `span` chip | **Strong** *(emerald pill, right-aligned)* |
| 573 | `span` | High confidence |
| 593 | `p` | Do they check their work, in the commit trail and while writing it? |
| 629 | `p` | Returns to their own defects and ships tests with the fix. |
| 670 | `span` | Returned to repair their own code and shipped a test with it. |
| 671 | `code` | 18da6f13 · src/ratelimit.py |
| 707 | `li` | — Based on one repository. |
| 781 | `h3` | Ownership |
| 783 | `span` chip | **Strong** *(emerald pill)* |
| 787 | `span` | High confidence |
| 807 | `p` | Do they return to fix their own defects, with tests, over time? *(cut at 813)* |
| ▸ 843 | `p` | Returns to their own defects and ships tests with the fix. |

Fold falls inside the second card. **Two verdict chips are visible, both "Strong".**

### Mobile — 390 × 844

| y | element | text |
|---|---|---|
| 56 | `p` eyebrow | ENGINEERING CAPABILITY PROFILE |
| 80 | `h1` | **alice@example.com** |
| 124–215 | `p` | Built from a git history … it does not make one. *(4 lines)* |
| 256 | `h2` | EVIDENCE INSPECTED |
| 276 | `p` | Stated before anything is concluded from it. |
| 316/334 | `dt`/`dd` | Repository · example/with-telemetry |
| 316/334 | `dt`/`dd` | Commits by subject · **12 of 14** |
| 370/388 | `dt`/`dd` | Diffs read · **14 of 14** |
| 370/388 | `dt`/`dd` | Active window · 2024-01-01 → 2024-02-20 |
| 444/462 | `dt`/`dd` | Measurements · **5 measured, 0 withheld** |
| 444/462 | `dt`/`dd` | Sessions · **20** |
| 498/516 | `dt`/`dd` | Head · 753b3cef |
| 498/516 | `dt`/`dd` | Excluded files · 1 docs, 1 lockfile |
| 617 | `h2` | DIMENSIONS |
| 637 | `p` | Reported side by side. There is no overall score. |
| 698 | `h3` | Verification discipline |
| 724–764 | `p` | Do they check their work, in the commit trail and while writing it? |
| 776 | `span` chip | **Strong** *(emerald pill; wraps below the heading at this width)* |
| 780 | `span` | High confidence |
| 816–862 | `p` | Returns to their own defects and ships tests with the fix. *(cut at 844)* |

Fold falls two lines into the first card's summary. **Exactly one verdict chip is visible,
and it is "Strong".**

---

## 3. Could a 4-second skim read any of that as a rank, grade, or verdict?

Item by item, above the fold.

**No — reads correctly:**

- The eyebrow, the intro paragraph, and "Reported side by side. There is no overall score."
  The disclaimer is above the fold at both widths, which is the right place for it.
- `Commits by subject 12 of 14`, `Diffs read 14 of 14`. Both carry a visible denominator in
  the value itself. A skimmer reads "coverage", which is what they are.
- `Active window`, `Head`, `Repository`, `Excluded files`. Provenance, not judgement.
- The claim text and its `18da6f13 · src/ratelimit.py` locator. Reads as a receipt.

**Yes — reads as a grade, in descending severity:**

1. **The verdict chip is a graded colour ramp.** `VERDICT_STYLES`
   (`web/lib/profile.ts:129`) assigns emerald → sky → amber → rose across
   `strong` → `moderate` → `limited` → `contradicted`. That is green-yellow-red. The
   comment above it defends the *declining* verdicts being neutral slate, and they are; the
   protection was applied to the wrong half. The four **conclusive** verdicts form a
   traffic-light scale, right-aligned in a column, one per card. At 4 seconds a reader takes
   the colour, not the word — and a column of green pills is a report card.

2. **Position 1 is read as the headline, and the ordering rule guarantees position 1 is the
   best-supported conclusion.** `order_findings` (`vouch/l5/ordering.py:106`) sorts by
   `(tier, -strength, fallback)`. `ordering.py:6` states the intent exactly: "Position is a
   claim. The first readout is the one a screener reads, quotes, and sometimes decides on."
   The rule is right and the reasoning for it is right. The consequence is still that
   whatever sits at the top of the page is consumed as a summary of the whole document —
   structurally the same slot the competitor labels "Overall signal", just unlabelled.
   Note that tier 0 contains `CONTRADICTED` alongside `STRONG`, so a well-evidenced
   *negative* finding can lead; in both shipped fixtures it does not, and both lead with a
   green "Strong".

3. **On mobile this collapses to a single visible verdict.** One dimension, one green pill,
   above the fold. Reported-side-by-side is the entire defence against a summary reading,
   and at 390px the side-by-side is not visible. A screener who never scrolls has seen
   `alice@example.com` and `Strong`.

4. **`Measurements · 5 measured, 0 withheld`** is the one above-the-fold number that reads
   as a score-like tally rather than coverage. "5 measured, 0 withheld" invites "5/5". It is
   not a rate and there is no denominator to divide by, but the pairing of two counts in one
   value does the work of one. See §5 — this is also the only place a MinN suppression
   surfaces above the fold, and it does not say that is what happened.

5. **`Sessions · 20`** is a bare count with no denominator and no floor. Low risk, but it is
   the only naked number in the block and reads as volume-of-evidence.

**Per-dimension numerics — the specific case in the brief:** there are **none**. A
`DimensionFinding` (`vouch/l4/schema.py:154`) carries `verdict`, `confidence`, `summary`,
`claims`, `limitations`, `risks_to_probe` — no value, no interval, no rate. `Profile` has no
`facts` field at all, so L1's `Fact` objects with their `value`/`interval`/`numerator`/
`denominator` never reach the viewer. The "0.0 next to verification discipline" failure mode
cannot occur in the current render because the number does not exist in the document. The
grade-shaped signal is carried entirely by chip colour and card position instead.

---

## 4. Do labels and ordering live in the document or the renderer?

**Labels: renderer. Ordering: document.** Proven, not asserted — script below.

| | location | in `frozen_payload()`? | relabelling breaks links? |
|---|---|---|---|
| Dimension titles | `web/lib/profile.ts:102` `DIMENSION_TITLES` | no | **no** |
| Dimension questions | `web/lib/profile.ts:109` `DIMENSION_QUESTIONS` | no | **no** |
| Verdict labels | `web/lib/profile.ts:118` `VERDICT_LABELS` | no | **no** |
| Verdict colours | `web/lib/profile.ts:129` `VERDICT_STYLES` | no | **no** |
| Confidence labels | `web/lib/profile.ts:146` `CONFIDENCE_LABELS` | no | **no** |
| Section headings | `web/components/Profile.tsx:159,207,215,231,254,266` (literals) | no | **no** |
| **Finding order** | `vouch/l5/ordering.py:106`, serialized as list order | **yes** | **yes — changes every id** |

The document stores enum values only (`"verification_discipline"`, `"strong"`, `"high"`).
`frozen_payload()` (`vouch/l5/profile.py:119`) canonicalises with `sort_keys=True`, which
sorts dict keys and **not** list elements, so `findings` order is hashed verbatim and
`compute_id()` (`:126`) folds it into `profile_id`.

Verification, run against both checked-in snapshots:

```
--- c873f3c18cfc7dc8
  label 'Verification discipline'  in hashed payload: False
  label 'Ownership'                in hashed payload: False
  label 'Strong'                   in hashed payload: False
  label 'High confidence'          in hashed payload: False
  reorder findings   -> af51f15cd3ff5b45   CHANGED
  move generated_at  -> (unchanged)        STABLE
```

**One exception, and it is a real one.** `derive_risks` (`vouch/l5/limitations.py:116`)
interpolates `DimensionSpec.title` from `vouch/l4/dimensions.py:56` into the risk sentences,
which *are* hashed:

```
--- 5c7e853845a45899
  label 'Planning discipline'      in hashed payload: True
  RISK: "Planning discipline could not be assessed from this evidence. Ask about it directly…"
```

So renaming a dimension in `web/lib/profile.ts` is free, but renaming it in
`vouch/l4/dimensions.py` changes `profile_id` for every profile that has a `not_collected`,
`insufficient_evidence`, or `contradicted` verdict — i.e. exactly the honest ones. The two
title sources are not kept in sync by anything.

### Incidental: the shipped snapshots' ids are already stale

Neither fixture's stored `profile_id` reproduces under today's code:

```
c873f3c18cfc7dc8  -> compute_id() = 4223a1911247f209
5c7e853845a45899  -> compute_id() = a5f36fffd8df45db
```

Cause: `Provenance.session_snapshot` (`vouch/l5/profile.py:92`) was added after these files
were written. Adding a defaulted field to a hashed model rewrites the payload for every
profile ever generated. Hashing `c873…`'s raw bytes as-is *does* reproduce its stored id, so
that one is internally consistent with the older schema; hashing `5c7e…`'s raw bytes gives
`ef9307616a0f828e`, matching neither — that file has been edited by hand since generation.
`tests/test_l5_profile.py:103` checks id stability only *within one process run*, so nothing
catches drift in a stored snapshot. This is the baseline Phase 2's "must not change
`profile_id`" requirement has to be proven against, and it is currently broken.

---

## 5. Numbers rendered below a MinN floor, and where the flag sits

**Floors that exist.** `MinN` (`vouch/l1/config.py:41`): `fix_commits=3`,
`subject_commits=10`, `latency_pairs=3`. `L2MinN` (`vouch/l2/metrics.py:48`). Below a floor,
`_apply_suppression` (`vouch/l1/extract.py:378`) sets `SUPPRESSED_LOW_N`, nulls `value`, and
keeps the interval. `_low_denominator_confound` (`:400`) then raises one repo-level
`low_denominator` confound at `WARN`.

**Every number the viewer renders, and its floor status:**

| # | rendered value | source | floor? | denominator visible? |
|---|---|---|---|---|
| 1 | `12 of 14` commits by subject | `Profile.tsx:166` | n/a — raw count | yes |
| 2 | `14 of 14` diffs read | `Profile.tsx:173` | n/a — raw count | yes |
| 3 | `5 measured, 0 withheld` | `Profile.tsx:187` | **aggregate of all suppression** | no |
| 4 | `20` sessions | `Profile.tsx:191` | none | n/a |
| 5 | `1 docs, 1 lockfile` excluded | `Profile.tsx:199` | none | n/a |
| 6 | `0 of 14` corroborated | `Profile.tsx:238` | **none anywhere in L3** | yes |
| 7 | `N verdict(s) downgraded` | `Profile.tsx:291` | n/a | no |
| 8 | risk ordinals `01`, `02` | `Profile.tsx:223` | n/a — not data | n/a |

**No suppressed rate is ever rendered.** `Profile` carries no `facts` list, so a
`SUPPRESSED_LOW_N` fact — its nulled value, its surviving interval, and its explanatory note
("no point estimate: 2 observation(s), below the floor of 3…") — reaches the viewer through
**no** path at all. The floors work; the reader never learns they fired, except as follows.

**Where the flag is, relative to the number it qualifies.** Three surfaces, at increasing
distance:

1. `Measurements · N measured, M withheld` — **above the fold**, y=385 desktop / y=462
   mobile. `withheld_facts` (`vouch/l5/profile.py:161`) counts *any* non-`MEASURED` status,
   so it collapses MinN suppression and confound invalidation into one number. A reader
   cannot tell "the history was too thin" from "a solo repo made this meaningless".
2. The `low_denominator` confound in **What could make these readings wrong**. In the solo
   fixture the confounds section renders at y=2481 (390px) — **2,042px below** the withheld
   count it explains. That section renders only when `confounds` is non-empty
   (`Profile.tsx:253`).
3. A derived limitation, "N measurement(s) were withheld for want of a large enough
   denominator (…). A rate that thin is not reported rather than rounded."
   (`vouch/l5/limitations.py:67`) — in **Limitations**, y=2747 (390px), the last section
   before the footer.

**Neither shipped snapshot exercises this.** `c873…` has no confounds; `5c7e…` has
`solo_repo` (invalidating), not `low_denominator`. The low-N presentation path has no
rendered example in the repo, so nothing visual has ever been reviewed for it.

**One ratio with no floor at all.** `0 of 14 commits have session evidence behind them`
(#6) is rendered in the same `X of Y` form as the floored counts, but `CorroborationReport`
(`vouch/l3/join.py:160`) defines no minimum denominator, and `coverage` (`:177`) divides
with only a zero-guard. At `n_commits=2` this renders "1 of 2" in the body text and repeats
it in Limitations. The denominator is visible, which is the invariant's main protection, but
this is the one place a small-n ratio reaches the page unfloored.

---

## Two findings outside the brief, noted because they surfaced during measurement

**The subject's local filesystem path is written into the shared document.**
`derive_limitations` (`vouch/l5/limitations.py:47`) interpolates `facts.repo` raw:

> "Based on a single repository (`/var/folders/qn/myx3dwjs6z55b5mhyxykjq3m0000gn/T/tmpad9a3c6d/repo`)
> and the 12 commits authored there by this person."

`facts.repo` is `snapshot.repo`, which is whatever was passed to `vouch profile`
(`vouch/ingest/__init__.py:148`) — a URL for a remote clone, an absolute local path for the
documented local flow. The header is defended (`Profile.tsx:164` truncates to the last two
segments); the limitation string is not. On a real local run this publishes
`/Users/<name>/Projects/<private-repo>` in a document with no login. Both fixtures show it,
which is also why `evidence_inspected.repo` reads `fixture://example/…` while the limitation
beside it reads a tmp path — the fixtures were sanitised in one place only.

**That same string causes a 130px horizontal overflow at 390px.** Document `scrollWidth` is
520 against a 390 viewport (517 on the solo fixture); the sole cause is the `li` at
`Profile.tsx:270` containing the unbreakable path token. No element's bounding box exceeds
the viewport — it is an unbreakable inline inside a normally-wrapped block. The whole
document scrolls sideways, so the header, the h1, and every verdict chip sit in a 520px
canvas on a 390px screen.

---

## Answer

**No leak of the competitor's kind.** There is no aggregate field, no derived render value,
and no way to compute one from what is rendered. The type-level guarantee holds and the
viewer respects it.

**A leak of a different kind, carried by presentation rather than data.** The document says
"there is no overall score" 20px above a column of colour-graded pills whose top entry is
structurally guaranteed to be the best-supported conclusion — and on a phone, only the top
entry is visible. What the competitor does with a label, this render does with position and
hue. `ordering.py` already names the mechanism: "Position is a claim."

---

## Addendum — 2026-07-29: the two findings outside the brief are fixed

*Appended, not merged into the audit above. Everything before this line describes the state
on 2026-07-28 and is left as written; the measurements there are still the record of what
was shipping when the audit ran.*

**The filesystem path is gone from the document.** `repo_url` is now normalized at the
ingest boundary — `repo_label()` (`vouch/ingest/__init__.py`) stores `org/repo` for a remote
and the leaf alone for a local path, so `evidence_inspected.repo` and the derived limitation
that quotes it (§ "Two findings outside the brief") carry a label rather than an address.
The real path stays in-process as `repo_path`. `SNAPSHOT_VERSION` and `EXTRACTOR_VERSION`
were bumped twice, once per rule change, so no cached entry serves the old value.

**The 130px overflow is gone.** Re-measured with the same method — real 390px and 320px
layout viewports inside an iframe, static export served over HTTP, headless Chrome —
document `scrollWidth` is 390 at 390 and 320 at 320 on both snapshots and the index. The
probe was validated against a copy of the fixed page with the old tmp path substituted back
in: 523, i.e. 133px over at 390 and 203px at 320.

**The stale-id finding was the load-bearing one.** § 4's incidental note — that neither
shipped snapshot reproduced its own `profile_id` — is now a test
(`test_web_share.py::test_stored_id_reproduces`), and it decided the migration: since the
content-hash promise was already broken, the fix regenerated both snapshots rather than
preserving links. Both ids in this document (`c873f3c18cfc7dc8`, `5c7e853845a45899`) are
retired. The hand-edited one was deleted and rebuilt from source by
`scripts/build_sample_profiles.py`; the other was scrubbed and rehashed.

**What the audit did not cover, and now has a control.** The normalizer only closes the
input side. `assert_no_machine_locals()` (`tests/conftest.py`) scans the finished document
— including the model's free text, which no normalizer reaches — against a fixed canary set
plus this machine's own home directory and hostname.

**Unchanged: everything in §§ 1–3.** The presentation-carried leak — the colour-graded
verdict ramp, position 1 as headline, one green pill above the fold at 390px — is untouched
by this work. That was the brief's actual question and it remains open.

---

## Addendum — 2026-07-30: the render moved under the measurements

*The viewer was rewritten (`fb7e670`) into numbered sections with copyable locator chips and
a stat grid that carries its denominators in the value. Nothing below is a re-measurement —
re-running the audit needs the geometry taken again.*

**Stale, and how much.** Every `y` in § 2 and every line-numbered reference into `web/`
(`Profile.tsx:NNN` in §§ 4–5, `web/README.md:29` in § 1) predates the rewrite and should be
read as a description of the old layout, not of today's. The claims at those locations still
hold; only the coordinates moved. The method itself also changed: there is no `web/out/` any more (profiles are
written by a worker after the build, so the export was dropped), so a re-measurement serves
`npm run build && npm start` instead of a static directory. The product pages moved to
`web/app/(site)/`; `/p/<id>` deliberately stayed outside that group and carries no nav.

**The finding is not stale.** `VERDICT_STYLES` still ramps emerald → sky → amber → rose
across `strong` → `moderate` → `limited` → `contradicted`, and the declining verdicts are
still the neutral half. `order_findings` still puts the best-supported conclusion first. So
§ 3's items 1–3 — the traffic-light ramp, position 1 read as a headline, one pill above the
fold at 390px — survive the restyle, which the commit that made it says in as many words.

**The ids moved again, as designed.** The snapshots this audit measured are gone twice over:
`c873…`/`5c7e…` were retired by the 07-29 regeneration and the files are now
`e5289e0775c2c373` (with-telemetry) and `29ea47da5e6c6137` (git-only solo). A new id per
regeneration is the frozen-snapshot contract working, not drifting.

**Still true and still unexercised:** neither shipped snapshot contains a `low_denominator`
confound (§ 5), so the low-n presentation path has no rendered example in the repo.
