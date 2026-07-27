"""The blind labelling harness — how `eval/labels.yaml` stops being empty.

Ground truth for this product is one careful human's judgement of a real engineer's history.
Three things decide whether that judgement is worth scoring a model against, and all three
are properties of the *procedure*, not of the labeller's good intentions.

**Blind.** The labeller never sees the judge's verdict. Shown a model's answer first, a
human agrees with it far more often than they would have unprompted, and the eval then
measures how persuasive the model is rather than how right it is. :func:`build_task` is
constructed from L1 and L3 only; there is no code path by which an L4 finding reaches it.

**Split assigned before labelling, not after.** Which pool a row lands in is a deterministic
hash of `(corpus_id, dimension)` — decided before anyone looks at the evidence, and not
changeable by re-running. Choosing the split afterwards, however honestly, is how a holdout
stops being a holdout.

**Evidence, then the question.** Each task renders what was measured — with intervals, so
`0 of 5` reads as the range it is rather than as a zero — and the confounds that bear on
it, and then asks. A labeller who has already read "0%" cannot un-read it.

`insufficient_evidence` is offered as a first-class answer everywhere, because a corpus of
only conclusive labels teaches nothing about overclaiming, which is the failure the whole
quality bar exists to catch.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import yaml

from vouch.l1.facts import FactStatus, RepoFacts
from vouch.l3.join import CorroborationReport
from vouch.l4.dimensions import DIMENSIONS, DimensionSpec
from vouch.l4.schema import DimensionKey, Verdict

__all__ = [
    "SPLIT_HOLDOUT_SHARE",
    "LabelTask",
    "assign_split",
    "build_task",
    "render_task",
    "pending_tasks",
    "append_label",
]

#: Share of rows routed to the holdout. One third, so a twelve-row corpus times four
#: dimensions leaves a holdout large enough to report and a train pool large enough to
#: iterate against. Applied per (corpus_id, dimension), not per repo, so no single history
#: lands entirely on one side.
SPLIT_HOLDOUT_SHARE = 1 / 3


@dataclass
class LabelTask:
    """One question put to a human, and everything they get to see before answering."""

    corpus_id: str
    dimension: DimensionKey
    split: str  # "train" | "holdout" — assigned before the evidence is rendered
    title: str
    question: str
    evidence: list[str] = field(default_factory=list)
    confounds: list[str] = field(default_factory=list)
    corroboration: list[str] = field(default_factory=list)
    permitted: tuple[Verdict, ...] = tuple(Verdict)


def assign_split(corpus_id: str, dimension: DimensionKey) -> str:
    """Deterministic, and fixed before anyone reads the evidence.

    Hashed rather than randomised so it is reproducible from the id alone: a labeller who
    re-runs the tool gets the same assignment, and cannot reroll a row into the pool they
    would prefer it in.
    """
    digest = hashlib.sha256(f"{corpus_id}\0{dimension.value}".encode()).digest()
    # First four bytes as a fraction of the range — plenty of resolution for one threshold.
    fraction = int.from_bytes(digest[:4], "big") / 0xFFFFFFFF
    return "holdout" if fraction < SPLIT_HOLDOUT_SHARE else "train"


def _fact_line(facts: RepoFacts, key: str) -> str:
    fact = facts.fact(key)
    if fact is None:
        return f"  {key}: not computed"

    unit = "" if fact.unit.value == "fraction" else f" {fact.unit.value}"
    denom = (
        f"{fact.numerator}/{fact.denominator}"
        if fact.numerator is not None
        else f"{fact.denominator} observation(s)"
    )
    if fact.interval is not None:
        band = f"{fact.interval.low:g}-{fact.interval.high:g}{unit}"
    else:
        band = "no interval"

    if fact.status is FactStatus.MEASURED:
        return f"  {key}: {band}  (point estimate {fact.value}{unit}, from {denom})"
    if fact.status is FactStatus.SUPPRESSED_LOW_N:
        return f"  {key}: {band} from {denom} — too thin for a point estimate"
    return f"  {key}: not assessable — {fact.note}"


def build_task(
    spec: DimensionSpec,
    corpus_id: str,
    facts: RepoFacts,
    corroboration: CorroborationReport | None = None,
) -> LabelTask:
    """Assemble one blind labelling task.

    Takes `RepoFacts` and a `CorroborationReport` — L1 and L3, and nothing else. There is
    deliberately no parameter an L4 finding could arrive through, so "just show the
    labeller what the model said" is not an option a future caller can reach for.
    """
    evidence = [_fact_line(facts, key) for key in spec.l1_facts]
    if not spec.l1_facts:
        evidence = ["  (no commit-trail facts feed this dimension)"]
    evidence.append(
        f"  subject activity: {facts.n_commits_by_subject} of "
        f"{facts.n_commits_total} commits, {facts.window_first} to {facts.window_last}"
    )

    relevant = [c for c in facts.confounds if set(c.affects) & set(spec.l1_facts)]
    confounds = [
        f"  [{c.severity.value}] {c.key.value} ({c.direction.value}): {c.detail}"
        for c in relevant
    ] or ["  (none bearing on this dimension)"]

    corr: list[str] = []
    if corroboration is not None:
        corr = [
            f"  {corroboration.n_corroborated} of {corroboration.n_commits} commits have "
            f"session evidence ({corroboration.n_ambiguous} ambiguous). This is a count, "
            f"not an accuracy claim.",
        ]
        if corroboration.path_coverage.n_dropped:
            corr.append(
                f"  {corroboration.path_coverage.n_dropped} edited path(s) could not be "
                f"placed, so coverage here is a floor."
            )

    return LabelTask(
        corpus_id=corpus_id,
        dimension=spec.key,
        split=assign_split(corpus_id, spec.key),
        title=spec.title,
        question=spec.question,
        evidence=evidence,
        confounds=confounds,
        corroboration=corr,
    )


def render_task(task: LabelTask) -> str:
    """What the labeller reads. Evidence first, the question last, no model output ever."""
    lines = [
        "=" * 78,
        f"{task.corpus_id}  —  {task.title}   [{task.split}]",
        "=" * 78,
        "",
        "MEASURED",
        *task.evidence,
        "",
        "CONFOUNDS",
        *task.confounds,
    ]
    if task.corroboration:
        lines += ["", "SESSION CORROBORATION", *task.corroboration]
    lines += [
        "",
        "-" * 78,
        f"QUESTION: {task.question}",
        "",
        "  " + " | ".join(v.value for v in task.permitted),
        "",
        "`insufficient_evidence` is a real answer and is expected to be common. Declining",
        "where a conclusion is not earned is what this corpus most needs recorded.",
        "",
    ]
    return "\n".join(lines)


def pending_tasks(labelled: set[tuple[str, DimensionKey]], corpus_ids: list[str]):
    """Every (corpus row, dimension) pair not yet labelled, in a stable order."""
    for corpus_id in corpus_ids:
        for spec in DIMENSIONS:
            if (corpus_id, spec.key) not in labelled:
                yield corpus_id, spec


def append_label(
    path,
    corpus_id: str,
    dimension: DimensionKey,
    verdict: Verdict,
    reason: str,
    split: str,
) -> None:
    """Append one label to its pool, rewriting the file in place.

    Read-modify-write rather than a plain append, because the file has two pools and a
    label belongs to whichever the split assigned — not to whichever happens to be last.
    """
    raw = yaml.safe_load(path.read_text()) if path.is_file() else None
    data = raw if isinstance(raw, dict) else {}
    data.setdefault("train", [])
    data.setdefault("holdout", [])
    data[split] = list(data[split] or []) + [
        {
            "corpus_id": corpus_id,
            "dimension": dimension.value,
            "verdict": verdict.value,
            "reason": reason.strip(),
        }
    ]
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
