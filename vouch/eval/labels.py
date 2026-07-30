"""Label schema + train/holdout split.

Ported from the v0 harness, which had the disciplines right even though its types no longer
fit. What carries over unchanged:

* **The split lives in the data, not the harness.** You can see at a glance which repos are
  burned for prompt iteration and which are held in reserve.
* **Every label carries a required, non-blank `reason`** — a falsifiable one-liner a
  sceptic could check against the history. A label without one is a guess, and loading
  fails loud rather than scoring against unjustified ground truth.

What changed: a label is now per **dimension**, and its verdict is drawn from L4's enum
rather than a strong/weak binary. `insufficient_evidence` is a legitimate ground-truth
label — "a careful human would decline to conclude here" is exactly the judgement we most
need the model to reproduce.

**A label is keyed on a corpus id, never on a person.** `eval/repos.yaml` already stores a
*selector* — the n-th most prolific non-bot author at a pinned head, guarded by a digest —
precisely so that no third-party address enters this repository. A label file keyed on
`(repo_url, author_email)` would have undone that in one line, and would have done it in the
file whose entire purpose is to record judgements about the people named in it. The id is
the join key; the address is resolved from the clone at the moment it is needed, by
:mod:`vouch.eval.corpus`, and is never written down.

This is enforced, not documented: :func:`load_labels` rejects a file containing anything
shaped like an email address, wherever it appears — including inside a `reason`, which is
free text a human writes by hand and is exactly where one would slip in.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from vouch.l4.dimensions import DIMENSIONS
from vouch.l4.schema import DimensionKey, Verdict
from vouch.privacy import contains_address, find_addresses

__all__ = [
    "LabelValidationError",
    "NO_MEASURE",
    "DimensionLabel",
    "LabelProvenance",
    "LabelSet",
    "load_labels",
    "permitted_measures",
]

#: `leaned_on` when the verdict rested on nothing. Spelled out: an empty list reads as unfilled.
NO_MEASURE = "none"


def permitted_measures(dimension: DimensionKey) -> set[str]:
    """Every measure a label for this dimension may say it leaned on.

    Read off the dimension's own declaration, so a fact added to a dimension is immediately
    citable and a fact removed from one immediately is not.
    """
    spec = next(s for s in DIMENSIONS if s.key is dimension)
    return {*spec.l1_facts, *(m.value for m in spec.l2_metrics), NO_MEASURE}


class LabelValidationError(Exception):
    """A label file is malformed, or the holdout has leaked into train."""


class DimensionLabel(BaseModel):
    """One frozen judgement: what a careful human says about this dimension, and why.

    ``corpus_id`` is the only identifier. There is no `repo`, no `author` and no `aliases`
    field, because a field that can hold an address eventually holds one — the guarantee is
    the absent field, not the discipline of whoever fills the file in.

    ``leaned_on`` exists because some dimensions rest on several measures and **nothing
    anywhere says how to combine them**. `ownership` is `ownership_loop` + `followup_latency`
    + `revert_rate`; on httpx those are a flattering 0.85 under a squash warning, 92 days,
    and 0.002, and no rule in this codebase says what verdict that adds up to. Two labellers
    — or the same one on two days — can reach different verdicts there without either being
    careless.

    The rule is deliberately *not* defined here. Inventing a weighting to make the corpus
    tidy would bake one person's intuition into the ground truth and then score the judge
    against it. Recording which measure the judgement actually rested on turns the
    underspecification into data instead: if the ownership labels split by which fact was
    leaned on, that is a finding about the dimension, visible in the corpus rather than
    hidden inside it.
    """

    model_config = ConfigDict(extra="forbid")

    corpus_id: str  # a row id in eval/repos.yaml; resolves to a person at run time
    dimension: DimensionKey
    verdict: Verdict
    reason: str  # REQUIRED, non-blank
    #: Required, non-empty: a measure key this dimension declares, or `none` on its own.
    leaned_on: list[str]

    @field_validator("reason")
    @classmethod
    def _reason_present(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError(
                "reason is required and must be a non-blank, falsifiable one-liner"
            )
        if contains_address(v):
            raise ValueError(
                "reason contains something shaped like an email address. Labels are keyed "
                "on corpus_id and no address belongs in this file — refer to the subject "
                "as 'the subject' or by corpus id."
            )
        return v.strip()

    @field_validator("corpus_id")
    @classmethod
    def _id_is_an_id(cls, v: str) -> str:
        if contains_address(v):
            raise ValueError(
                f"corpus_id {v!r} is an email address. It must be a row id from "
                "eval/repos.yaml, which resolves to a person only against a clone."
            )
        return v

    @model_validator(mode="after")
    def _leaned_on_names_this_dimension_evidence(self) -> DimensionLabel:
        if not self.leaned_on:
            raise ValueError(
                "leaned_on is required: name the measure this verdict rested on, or "
                f"['{NO_MEASURE}'] if it rested on none"
            )
        if NO_MEASURE in self.leaned_on and len(self.leaned_on) > 1:
            raise ValueError(
                f"leaned_on has '{NO_MEASURE}' alongside a measure. It means the verdict "
                "rested on no measure at all, so it cannot share the field."
            )
        permitted = permitted_measures(self.dimension)
        unknown = [k for k in self.leaned_on if k not in permitted]
        if unknown:
            raise ValueError(
                f"leaned_on names {unknown}, which {self.dimension.value} does not rest on. "
                f"Expected any of: {', '.join(sorted(permitted))}."
            )
        return self

    @property
    def key(self) -> tuple[str, DimensionKey]:
        return (self.corpus_id, self.dimension)


class LabelProvenance(BaseModel):
    """The code the labels were made against.

    A calibration result that cannot name the code it measured is not a result. ``code_sha``
    is the record a reader can go and check out.

    ``extractor_version``, ``l1_config`` and ``render_version`` matter for a different and
    sharper reason: they decide whether labels still *apply*. A label is a human's judgement
    of the evidence they were shown, and those three are what determine what was on the
    screen. Bump any of them and the same corpus row renders differently — so the existing
    labels were made against a rendering that no longer exists, and carrying them forward
    silently would score the judge against ground truth for a different question.

    ``render_version`` REVERSES an earlier decision recorded here, which was that no
    rendering version belonged in this file because a label is a reading of the evidence and
    not of any prompt. The evidence for the reversal is a bug: the harness rendered a
    dimension's L1 facts and silently dropped its L2 metrics, so labels made before that fix
    answer a materially narrower question than labels made after it — with an identical
    ``extractor_version`` and an identical ``l1_config``, because neither the numbers nor the
    config changed. The rendering is part of what a label is a judgement of, and nothing else
    here was able to say so.

    There is still deliberately no ``prompt_version``: how the *judge* is prompted has no
    bearing on what a human was shown. The eval run records that, which is where it belongs.
    """

    model_config = ConfigDict(extra="forbid")

    code_sha: str = ""
    dirty: bool = False  # labelled against uncommitted changes; the sha does not describe it
    extractor_version: str = ""
    l1_config: str = ""
    render_version: str = ""  # the harness that drew the screen the labeller read

    def differs_from(self, other: LabelProvenance) -> list[str]:
        """Which fields would change what a labeller was shown. Empty means compatible."""
        return [
            name
            for name in ("extractor_version", "l1_config", "render_version")
            if getattr(self, name) and getattr(other, name)
            and getattr(self, name) != getattr(other, name)
        ]


class LabelSet(BaseModel):
    """The two disjoint pools."""

    model_config = ConfigDict(extra="forbid")

    metadata: LabelProvenance = Field(default_factory=LabelProvenance)
    train: list[DimensionLabel] = Field(default_factory=list)
    holdout: list[DimensionLabel] = Field(default_factory=list)

    def all_rows(self) -> list[DimensionLabel]:
        return [*self.train, *self.holdout]

    @property
    def total(self) -> int:
        return len(self.train) + len(self.holdout)


def load_labels(
    path: Path, known_ids: set[str] | None = None
) -> LabelSet:
    """Load and validate a label file. Raises rather than silently accepting a bad one.

    ``known_ids`` is the set of ids in ``eval/repos.yaml``; when supplied, every label must
    name one of them.
    """
    if not path.is_file():
        raise FileNotFoundError(f"no label file at {path}")

    text = path.read_text()

    # Raw bytes, before parsing: a YAML comment is a leak the schema would never see.
    if found := sorted(set(find_addresses(text))):
        raise LabelValidationError(
            f"{path}: contains {len(found)} email-shaped string(s) "
            f"(first: {found[0].split('@')[0][:3]}...@...). Labels are keyed on "
            "corpus_id — an id from eval/repos.yaml — and no third-party address may "
            "enter this repository's history, in a field or in a comment."
        )

    try:
        raw = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise LabelValidationError(f"{path}: not valid YAML: {e}") from e

    if not isinstance(raw, dict) or not {"train", "holdout"} <= set(raw):
        raise LabelValidationError(
            f"{path}: expected top-level 'train:' and 'holdout:' pools"
        )

    try:
        labels = LabelSet.model_validate(
            {
                "metadata": raw.get("metadata") or {},
                "train": raw.get("train") or [],
                "holdout": raw.get("holdout") or [],
            }
        )
    except Exception as e:
        raise LabelValidationError(f"{path}: {e}") from e

    # A row in both pools makes the holdout number meaningless — the prompt was tuned on it.
    leaked = {row.key for row in labels.train} & {row.key for row in labels.holdout}
    if leaked:
        raise LabelValidationError(
            f"{path}: {len(leaked)} label(s) appear in BOTH train and holdout: "
            f"{sorted(str(k) for k in leaked)}. The holdout must never be tuned on."
        )

    if known_ids is not None:
        # An id is only a join key if it joins; a typo would surface as an unscored row.
        unknown = sorted({r.corpus_id for r in labels.all_rows()} - set(known_ids))
        if unknown:
            raise LabelValidationError(
                f"{path}: {len(unknown)} label(s) name a corpus id that does not exist "
                f"in the corpus: {unknown}."
            )

    # An empty file has no result to attribute yet; one label in, the code must be named.
    if labels.total and not labels.metadata.code_sha:
        raise LabelValidationError(
            f"{path}: {labels.total} label(s) with no `metadata.code_sha`. A calibration "
            "result that cannot name the code it measured is not a result. `vouch label` "
            "stamps this on the first write; add it by hand if the file was written "
            "another way."
        )

    return labels
