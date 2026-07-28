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

**The whole question, or none of it.** A dimension's question is answered from every layer
the dimension declares, so the task renders every layer. This is not a tidiness point: the
harness previously rendered `spec.l1_facts` and silently dropped `spec.l2_metrics`, so
`verification_discipline` asked "in the commit trail *and while working*?" over commit-trail
evidence alone, and a label recorded against that answer is ground truth for a narrower
question than the one the judge is scored on. Where a layer is absent the task says so in
the layer's own section, rather than omitting the section — an omission reads as "nothing to
say here", which is a claim, and the wrong one.

`insufficient_evidence` is offered as a first-class answer everywhere, because a corpus of
only conclusive labels teaches nothing about overclaiming, which is the failure the whole
quality bar exists to catch.

**What is not a judgement call is not offered as one.** Whether a dimension *can* be
assessed here is decided by :func:`vouch.l4.dimensions.assess_availability`, deterministically
and before the evidence is drawn — the same function that decides it for the judge. When it
says the input layer was absent, the task says so and permits exactly one answer. Leaving
`not_collected` sitting in the middle of a seven-option menu invited two failures at once: a
labeller picking it where evidence did exist, and a labeller picking `insufficient_evidence`
where nothing had been looked at — the two the verdict enum exists to keep apart. The
converse holds too: where a layer *was* read, "we did not look" is not an admissible answer
and does not appear on the menu at all.
"""
from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from vouch.eval.labels import LabelProvenance
from vouch.l1.cache import EXTRACTOR_VERSION
from vouch.l1.config import L1_CONFIG
from vouch.l1.facts import FactStatus, RepoFacts
from vouch.l1.interval import Polarity
from vouch.l2.metrics import METRIC_POLARITY
from vouch.l2.payload import MetricKey, SessionMetrics
from vouch.l3.join import CorroborationReport
from vouch.l4.dimensions import DIMENSIONS, DimensionSpec, assess_availability
from vouch.l4.schema import DimensionKey, Verdict

__all__ = [
    "SPLIT_HOLDOUT_SHARE",
    "JUDGEABLE_VERDICTS",
    "LabelTask",
    "assign_split",
    "build_task",
    "render_task",
    "pending_tasks",
    "current_provenance",
    "append_label",
]

#: Share of rows routed to the holdout. One third, so a twelve-row corpus times four
#: dimensions leaves a holdout large enough to report and a train pool large enough to
#: iterate against. Applied per (corpus_id, dimension), not per repo, so no single history
#: lands entirely on one side.
SPLIT_HOLDOUT_SHARE = 1 / 3

#: The verdicts a human is entitled to reach by reading evidence. The other two are
#: statements about whether there was anything to read, which `assess_availability` decides
#: before the labeller sees the row — so they are forced when they apply and absent when
#: they do not, never sitting on the menu as a third kind of thing to pick.
JUDGEABLE_VERDICTS: tuple[Verdict, ...] = tuple(
    v for v in Verdict if v not in (Verdict.NOT_ASSESSED, Verdict.NOT_ASSESSABLE)
)


@dataclass
class LabelTask:
    """One question put to a human, and everything they get to see before answering."""

    corpus_id: str
    dimension: DimensionKey
    split: str  # "train" | "holdout" — assigned before the evidence is rendered
    title: str
    question: str
    evidence: list[str] = field(default_factory=list)
    #: The session-trail half. Kept separate from ``evidence`` rather than concatenated so
    #: that a dimension reading from both layers cannot render as though it read from one.
    session: list[str] = field(default_factory=list)
    confounds: list[str] = field(default_factory=list)
    corroboration: list[str] = field(default_factory=list)
    #: The answers this task will accept. Narrowed to one when availability, not judgement,
    #: settles the dimension; otherwise every verdict a human is entitled to reach.
    permitted: tuple[Verdict, ...] = JUDGEABLE_VERDICTS
    #: Why the answer is forced, in the labeller's terms. Empty when it is not.
    forced_reason: str = ""

    @property
    def is_forced(self) -> bool:
        return len(self.permitted) == 1


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


#: How each polarity reads to a human. `neutral` is spelled out rather than left blank: a
#: missing note is indistinguishable from a forgotten one, and `commit_scoping` genuinely
#: has no better direction — small commits are focused or trivial, large ones thorough or
#: sprawling.
_DIRECTION = {
    Polarity.HIGHER_IS_BETTER: "higher is better",
    Polarity.LOWER_IS_BETTER: "lower is better",
    Polarity.NEUTRAL: "neither direction is better",
}


def _band(low: float | None, high: float | None, unit: str) -> str:
    if low is None or high is None:
        return "no interval"
    return f"{low:g}-{high:g}{unit}"


def _direction(polarity: Polarity) -> str:
    """Which way to read the number that precedes this.

    Direction travels with every measure because without it the measure is not
    interpretable: `followup_latency: 92 days` is a complaint or a compliment depending on
    an answer the labeller was never shown, and they will supply one from intuition if the
    render does not. It is also the asymmetry the interval itself was drawn on — the end
    that would read badly for the subject was held to the stricter confidence level — so a
    reader who does not know the direction cannot know which end was made harder to reach.
    """
    return f"  [{_DIRECTION[polarity]}]"


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
    interval = fact.interval
    band = _band(
        interval.low if interval else None, interval.high if interval else None, unit
    )

    way = _direction(fact.polarity)
    if fact.status is FactStatus.MEASURED:
        return f"  {key}: {band}  (point estimate {fact.value}{unit}, from {denom}){way}"
    if fact.status is FactStatus.SUPPRESSED_LOW_N:
        return f"  {key}: {band} from {denom} — too thin for a point estimate{way}"
    return f"  {key}: not assessable — {fact.note}"


def _metric_line(metrics: SessionMetrics | None, key: MetricKey) -> str:
    """One L2 metric, or a plain statement of why there is no number for it.

    The absent cases are spelled out rather than skipped. `plan_before_execute` missing
    because the CLI was never run and `plan_before_execute` missing because five sessions
    were not enough to divide by are different facts about this subject, and a labeller who
    is shown neither line cannot tell which one they are looking at.
    """
    if metrics is None:
        return f"  {key.value}: no session telemetry was supplied for this row"
    if metrics.degraded:
        return (
            f"  {key.value}: session telemetry was supplied but could not be read "
            f"({metrics.degraded_reason.value})"
        )

    rate = metrics.rates.get(key)
    if rate is None:
        return f"  {key.value}: not computed"

    band = _band(rate.low, rate.high, "")
    denom = f"{rate.numerator}/{rate.denominator}"
    way = _direction(METRIC_POLARITY[key])
    if rate.suppressed:
        return (
            f"  {key.value}: {band} from {denom} — {rate.denominator} observation(s) is "
            f"under the floor of {rate.floor}, so there is no point estimate{way}"
        )
    return f"  {key.value}: {band}  (point estimate {rate.value}, from {denom}){way}"


def build_task(
    spec: DimensionSpec,
    corpus_id: str,
    facts: RepoFacts,
    metrics: SessionMetrics | None = None,
    corroboration: CorroborationReport | None = None,
) -> LabelTask:
    """Assemble one blind labelling task.

    Takes `RepoFacts`, `SessionMetrics` and a `CorroborationReport` — L1, L2 and L3, and
    nothing else. There is deliberately no parameter an L4 finding could arrive through, so
    "just show the labeller what the model said" is not an option a future caller can reach
    for.

    ``metrics`` defaults to ``None`` because the common case genuinely has none — the
    calibration corpus is other people's public repositories, where no session log exists.
    That is rendered as the absence it is, not passed over.
    """
    evidence = [_fact_line(facts, key) for key in spec.l1_facts]
    if not spec.l1_facts:
        evidence = ["  (no commit-trail facts feed this dimension)"]
    evidence.append(
        f"  subject activity: {facts.n_commits_by_subject} of "
        f"{facts.n_commits_total} commits, {facts.window_first} to {facts.window_last}"
    )

    session = [_metric_line(metrics, key) for key in spec.l2_metrics]
    if not spec.l2_metrics:
        session = ["  (no session facts feed this dimension)"]

    relevant = [c for c in facts.confounds if set(c.affects) & set(spec.l1_facts)]
    confounds = [
        f"  [{c.severity.value}] {c.key.value} ({c.direction.value}): {c.detail}"
        for c in relevant
    ] or ["  (none bearing on this dimension)"]

    # The same call the judge makes, with the same inputs the labeller can see. Commit
    # judgments are zero by construction: they are L4's reading of the diffs, and no diff
    # text reaches this harness — so a dimension whose only remaining evidence would have
    # been the model's own diff reading is, to a labeller, unassessable.
    availability = assess_availability(spec, facts, metrics, n_commit_judgments=0)
    permitted, forced_reason = JUDGEABLE_VERDICTS, ""
    if availability.is_not_assessable:
        permitted = (Verdict.NOT_ASSESSABLE,)
        forced_reason = (
            "The only telemetry that could answer this was measured over a different "
            "population than this dimension claims, so it cannot describe work here. "
            "More evidence of the same kind would not help."
        )
    elif not availability.was_looked_at:
        permitted = (Verdict.NOT_ASSESSED,)
        forced_reason = (
            f"This dimension reads only from session telemetry "
            f"({', '.join(k.value for k in spec.l2_metrics)}), and none was collected for "
            "this row. Nothing was looked at, so there is no thinness to judge."
        )

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
        session=session,
        confounds=confounds,
        corroboration=corr,
        permitted=permitted,
        forced_reason=forced_reason,
    )


def render_task(task: LabelTask) -> str:
    """What the labeller reads. Evidence first, the question last, no model output ever."""
    lines = [
        "=" * 78,
        f"{task.corpus_id}  —  {task.title}   [{task.split}]",
        "=" * 78,
        "",
        "MEASURED — COMMIT TRAIL",
        *task.evidence,
        "",
        "MEASURED — SESSION TRAIL",
        *task.session,
        "",
        "CONFOUNDS",
        *task.confounds,
    ]
    if task.corroboration:
        lines += ["", "SESSION CORROBORATION", *task.corroboration]
    lines += ["", "-" * 78, f"QUESTION: {task.question}", ""]

    if task.is_forced:
        only = task.permitted[0].value
        lines += [
            "THIS DIMENSION CANNOT BE JUDGED HERE — the answer is not yours to pick.",
            f"  {task.forced_reason}",
            "",
            f"  the one admissible answer: {only}",
            "",
        ]
        return "\n".join(lines)

    lines += [
        "  " + " | ".join(v.value for v in task.permitted),
        "",
        "`insufficient_evidence` is a real answer and is expected to be common. Declining",
        "where a conclusion is not earned is what this corpus most needs recorded.",
        "",
    ]
    return "\n".join(lines)


def current_provenance(repo_root: Path | None = None) -> LabelProvenance:
    """What the labeller is about to be shown, described well enough to reproduce.

    ``dirty`` is recorded rather than refused. Labelling against a working tree is normal —
    the harness is usually being improved in the same sitting — but it means the SHA does
    not describe what was on screen, and a reader deserves to know that rather than trust a
    hash that is only approximately true.
    """
    root = repo_root or Path(__file__).resolve().parents[2]

    def git(*args: str) -> str:
        try:
            return subprocess.run(
                ["git", "-C", str(root), *args],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
        except (subprocess.CalledProcessError, OSError):
            return ""

    return LabelProvenance(
        code_sha=git("rev-parse", "HEAD"),
        dirty=bool(git("status", "--porcelain", "--untracked-files=no")),
        extractor_version=EXTRACTOR_VERSION,
        l1_config=L1_CONFIG.fingerprint(),
    )


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
    provenance: LabelProvenance | None = None,
) -> None:
    """Append one label to its pool, rewriting the file in place.

    Read-modify-write rather than a plain append, because the file has two pools and a
    label belongs to whichever the split assigned — not to whichever happens to be last.

    ``provenance`` is stamped on the first write and **checked** on every one after. If the
    extractor version or the L1 config has moved mid-round, the labels already in the file
    were made against numbers that no longer render, and mixing the two silently would give
    a pool whose rows answer subtly different questions. Refusing is the point.
    """
    raw = yaml.safe_load(path.read_text()) if path.is_file() else None
    data = raw if isinstance(raw, dict) else {}
    data.setdefault("train", [])
    data.setdefault("holdout", [])

    if provenance is not None:
        recorded = LabelProvenance.model_validate(data.get("metadata") or {})
        if drifted := provenance.differs_from(recorded):
            raise ValueError(
                f"the code moved mid-round ({', '.join(drifted)}): "
                f"{path} holds labels made against "
                f"{recorded.extractor_version}/{recorded.l1_config}, this run renders "
                f"{provenance.extractor_version}/{provenance.l1_config}. The evidence a "
                "labeller was shown has changed, so the two sets do not belong in one "
                "pool. Finish the round on the old code, or start a new file."
            )
        if not recorded.code_sha:
            data["metadata"] = provenance.model_dump()
    data[split] = list(data[split] or []) + [
        {
            "corpus_id": corpus_id,
            "dimension": dimension.value,
            "verdict": verdict.value,
            "reason": reason.strip(),
        }
    ]
    # Provenance first: it is the thing that decides whether anything below it still means
    # what it meant when it was written, so it should be the first thing a reader sees.
    ordered = {k: data[k] for k in ("metadata", "train", "holdout") if k in data}
    ordered.update({k: v for k, v in data.items() if k not in ordered})
    path.write_text(yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True))
