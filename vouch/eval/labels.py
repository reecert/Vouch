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

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from vouch.l4.schema import DimensionKey, Verdict

__all__ = [
    "LabelValidationError",
    "DimensionLabel",
    "LabelProvenance",
    "LabelSet",
    "load_labels",
]

#: Deliberately broad. A false positive here costs one rephrased `reason`; a false negative
#: puts somebody's address in a public git history, where deleting it later is not enough.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


class LabelValidationError(Exception):
    """A label file is malformed, or the holdout has leaked into train."""


class DimensionLabel(BaseModel):
    """One frozen judgement: what a careful human says about this dimension, and why.

    ``corpus_id`` is the only identifier. There is no `repo`, no `author` and no `aliases`
    field, because a field that can hold an address eventually holds one — the guarantee is
    the absent field, not the discipline of whoever fills the file in.
    """

    model_config = ConfigDict(extra="forbid")

    corpus_id: str  # a row id in eval/repos.yaml; resolves to a person at run time
    dimension: DimensionKey
    verdict: Verdict
    reason: str  # REQUIRED, non-blank

    @field_validator("reason")
    @classmethod
    def _reason_present(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError(
                "reason is required and must be a non-blank, falsifiable one-liner"
            )
        if _EMAIL_RE.search(v):
            raise ValueError(
                "reason contains something shaped like an email address. Labels are keyed "
                "on corpus_id and no address belongs in this file — refer to the subject "
                "as 'the subject' or by corpus id."
            )
        return v.strip()

    @field_validator("corpus_id")
    @classmethod
    def _id_is_an_id(cls, v: str) -> str:
        if _EMAIL_RE.search(v):
            raise ValueError(
                f"corpus_id {v!r} is an email address. It must be a row id from "
                "eval/repos.yaml, which resolves to a person only against a clone."
            )
        return v

    @property
    def key(self) -> tuple[str, DimensionKey]:
        return (self.corpus_id, self.dimension)


class LabelProvenance(BaseModel):
    """The code the labels were made against.

    A calibration result that cannot name the code it measured is not a result. ``code_sha``
    is the record a reader can go and check out.

    ``extractor_version`` and ``l1_config`` matter for a different and sharper reason: they
    decide whether labels still *apply*. A label is a human's judgement of the evidence they
    were shown, and those two are what determine the numbers on the screen. Bump either one
    and the same corpus row renders differently — so the existing labels were made against
    a rendering that no longer exists, and carrying them forward silently would score the
    judge against ground truth for a different question.
    """

    model_config = ConfigDict(extra="forbid")

    code_sha: str = ""
    dirty: bool = False  # labelled against uncommitted changes; the sha does not describe it
    extractor_version: str = ""
    l1_config: str = ""
    # Deliberately no `prompt_version`. A label is a human's reading of L1 evidence and does
    # not depend on how the judge is prompted; recording it here would imply otherwise. The
    # eval run records it, which is where it belongs.

    def differs_from(self, other: LabelProvenance) -> list[str]:
        """Which fields would change what a labeller was shown. Empty means compatible."""
        return [
            name
            for name in ("extractor_version", "l1_config")
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

    # Checked against the raw bytes, before parsing. A field the schema would reject is
    # still a leak the moment the file is committed, and comments are not parsed at all.
    if found := sorted(set(_EMAIL_RE.findall(text))):
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
        # An id is only a join key if it joins. A typo would otherwise surface much later,
        # as a row the harness silently could not score.
        unknown = sorted({r.corpus_id for r in labels.all_rows()} - set(known_ids))
        if unknown:
            raise LabelValidationError(
                f"{path}: {len(unknown)} label(s) name a corpus id that does not exist "
                f"in the corpus: {unknown}."
            )

    # An empty file needs no provenance — there is no result to attribute yet. The moment
    # there is one, it must name the code it was made against, or the agreement number it
    # eventually produces describes nothing in particular.
    if labels.total and not labels.metadata.code_sha:
        raise LabelValidationError(
            f"{path}: {labels.total} label(s) with no `metadata.code_sha`. A calibration "
            "result that cannot name the code it measured is not a result. `vouch label` "
            "stamps this on the first write; add it by hand if the file was written "
            "another way."
        )

    return labels
