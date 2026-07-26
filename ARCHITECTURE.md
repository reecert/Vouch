# Architecture

> **Superseded.** This file documented the v0 prototype: a single-dimension (ownership)
> pipeline whose judge saw only pre-computed metadata. That design is gone — its modules
> (`vouch/extract/`, `vouch/judge/`, `vouch/report/`) were deleted once L4 landed.
>
> **The current architecture lives in [`docs/plan.md`](docs/plan.md).**

One reversal is worth calling out here rather than leaving buried, because this file
asserted the opposite as a hard rule for the life of the prototype:

> *v0 non-goal: "No raw diffs sent to the model. Ever."*

L4 sends diffs. Whether a fix was real or cosmetic, and whether a test exercises the
failure it claims to, are not answerable from metadata — and those questions are the
product. The anti-hallucination guarantee was rebuilt rather than abandoned: the model may
read diff text, but it may only *cite* commits and paths it was actually shown, and the
grounding validator now checks the path as well as the SHA. Phase 1 is public repos only,
so the diff content is already public; private-repo support would need this revisited
before it ships.

See `docs/plan.md` §1.4 for the full reasoning and §2 for the five-layer design.
