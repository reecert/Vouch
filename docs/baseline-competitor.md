# Quality baseline — [competitor]

**Source:** competitor marketing homepage + the "illustrative profile" section it
renders inline.

**Coverage caveat.** Everything past `/auth/sign-in` is gated, so this is the public surface only:
the homepage, its illustrative profile, and the linked policy pages (`/terms`, `/privacy`,
`/ai-disclosure`, `/subprocessors`). There is no public pricing page and no full sample report. The
section list below is the one the homepage advertises; the real product may render more. Quoted
strings are verbatim marketing copy; everything else is my read and is marked as such.

---

## 1. What it is

> "selected engineering work into a readable hiring profile: what they built, how they reasoned,
> where the evidence is thin, and what to probe next."

Positioned at **founders and engineering leaders evaluating candidates** — the buyer is the hiring
side. The candidate-side pitch is consent-framed:

> "Your work. Your consent. A better application."

> "The resume gets the interview. It can't explain the work."

Three stated entry flows, all employer-initiated or employer-received:

- "Post a job. Receive candidate-consented profiles"
- "Bring someone you found. Submit an attested public GitHub profile"
- "Open your directory. Receive opt-in candidate submissions"

**Read:** this is a two-sided marketplace with the profile as the artifact. Our phase 1 is
deliberately the single-player half of that (profile generation + share link) and nothing else.

## 2. Report structure — the section list, in order

1. Overall signal
2. Evidence inspected
3. Trajectory
4. Startup Fit
5. Qualification Fit
6. What they built
7. Work experience
8. Flags
9. Impact proxies
10. Risks to probe
11. Limitations
12. Interview follow-up

Notes on individual sections:

- **Evidence inspected** sits at position 2 — before any judgment. The provenance is a
  headline, not an appendix.
- **What they built** is per-repository cards carrying deployment status, tech stack, analysis.
- **Work experience** is explicitly labelled **"self-reported, unverified"** and kept separate
  from the derived sections.
- **Risks to probe** and **Limitations** are standing sections, not conditional ones.

## 3. Capability dimensions

Top-level:

- Systems thinking
- Code quality
- Ownership
- Shipping & finishing
- End-to-end range
- Iteration after launch
- Pragmatism
- Corroborated experience
- AI collaboration

"Startup Fit" is a grouping over a subset (Builder-operator, Shipping & finishing, End-to-end
range, Iteration after launch, Pragmatism, Corroborated experience, AI collaboration) rather than
a dimension of its own. "Qualification Fit" is scored against role-specific priorities.

**AI collaboration** decomposes into five sub-dimensions:

- Verification & error recovery
- Ownership & direction
- Planning & scoping
- Evidence-driven iteration
- Tooling investment

**Read — this is the head-to-head axis.** "AI collaboration" is their name for our L2, and
"Corroborated experience" is their name for our L3. Their AI-collaboration metrics are read from
"connected tool sessions"; their corroboration language ("Not inferred from GitHub alone") implies a
join between session evidence and repo evidence. We are not entering an empty category — we are
entering theirs, and the differentiator has to be the *accuracy and auditability of the join* (L3),
not the existence of session metrics.

## 4. Rating and confidence language

Two separate vocabularies, used at different levels:

| Level | Vocabulary |
|---|---|
| Dimension verdict | "Strong", "Moderate", "Partial fit", "Insufficient evidence" |
| Signal confidence | "High confidence", "Moderate confidence" |

There is **no numeric score and no overall rank** anywhere in the public surface. Dimensions get a
word plus a one-line behavioural sentence:

- Systems thinking (Strong): "Models failure modes before they ship."
- Code quality (Strong): "Separates state, side effects, and recovery paths."
- Ownership (Moderate): "Returns after launch to close reliability gaps."

The overall signal is a sentence that names the gap rather than a grade:

> "Real systems depth; ownership under pressure still unverified."

Scope-limiting phrases, verbatim:

> "does not claim production impact beyond observable repository signals"

> "remains descriptive rather than predictive"

> "The evidence supports…Probe [X] before treating the fit as complete"

> "Not inferred from GitHub alone"

Raw counters are shown unrounded and un-narrativised in the AI collaboration block:

- Sessions: 18
- Verified after edits: 72%
- Planned before editing: 61%
- Prompts per chat: 8
- Chats per active day: 1.4

**Read:** the design rule to steal is *the qualitative band carries the claim; the number carries
the evidence.* Notice they publish `Sessions: 18` — a small n, stated plainly, next to percentages
derived from it. They do not hide the denominator. They also do not appear to gate the percentages
behind a minimum n, which is a place we can be stricter than them.

## 5. Trust guarantees

Four named guarantees, verbatim:

> **"No black-box rank"** — "[Competitor] supports a hiring decision. It does not make one."

> **"Visible uncertainty"** — "Thin or missing evidence stays insufficient instead of becoming a
> flattering conclusion."

> **"Private by default"** — "Applications and directory submissions share frozen profile
> projections, not a live candidate profile."

> **"Bounded inputs"** — "Candidates select repositories. Claude Code signals are optional and
> collected through a local consented flow."

Plus the consent flow:

> "Candidates choose the repositories that represent their work, explicitly generate a private
> profile, and consent when using it."

**Read:** "frozen profile projections, not a live candidate profile" is the sharpest of the four and
is a *product* decision, not a policy one — a share link resolves to an immutable snapshot, so the
recipient cannot watch the subject's ongoing activity. We should copy this outright. "Visible
uncertainty" is almost verbatim the brief's own `insufficient_evidence` requirement, which means
that requirement is table stakes rather than differentiation.

## 6. Stated limitations

> "This profile is based on selected repositories only."

> "No private production logs, employer references, or live pair-programming evidence were used."

> "AI collaboration is read from connected tool sessions; repos without linked sessions are not
> assessed for AI style."

> "Does not make [hiring decisions]"

**Read:** the third one is the important one — an explicit *per-section* coverage statement, not a
global disclaimer. A repo with no linked session is stated to be unassessed for AI style rather than
silently scored. That is the shape our L3 output needs: corroborated vs. uncorroborated must be a
visible property of each claim, not a footnote.

## 7. Onboarding and data

- Data in: candidate-selected GitHub repositories, optionally linked Claude Code tool sessions.
- Session collection: "a local consented flow".
- No pricing disclosed publicly.

## 8. What we have to match, and where we can beat it

**Match (table stakes — a report without these reads as worse than theirs):**

- Qualitative bands, no numeric score, no overall rank.
- "Insufficient evidence" as a normal outcome with its own band.
- Standing Limitations and Risks-to-probe sections.
- Evidence-inspected stated up front.
- Frozen share snapshots.
- Verified/derived evidence held separately from self-reported claims.

**Beat (the places their public surface is thin):**

1. **The join is asserted, not shown.** "Corroborated experience" is a dimension name; nothing in
   the public copy explains how a session is matched to a commit or how confident that match is. If
   L3 emits a per-commit corroboration record with its own match quality, that is inspectable
   evidence where theirs is a label.
2. **No confound disclosure.** Nothing addresses squash-merge histories, solo repos, bot commits, or
   rebase-rewritten authorship — all of which silently distort exactly the ownership-style signals
   they report. An explicit "what would make this reading wrong" block is a real differentiator and
   is the thing our L1 already has to compute anyway.
3. **No stated minimum-n discipline.** `Sessions: 18` yields five percentages with no visible floor
   below which a percentage is suppressed. We can suppress instead of rounding.
4. **Metadata-level vs. diff-level judgment.** Their behavioural sentences ("Separates state, side
   effects, and recovery paths") are the kind of claim that either comes from reading diffs or is
   unfalsifiable. L4 reading actual diffs and citing SHA + file path per claim is checkable in a way
   a prose sentence is not.

**Do not copy:** the two-sided marketplace surface (job posts, directory, employer workspaces) —
that is explicitly out of scope for phase 1.
