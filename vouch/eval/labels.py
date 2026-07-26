"""Label schema + train/holdout split for the eval harness.

The frozen ground truth lives in ``eval/labels.yaml``, split into two disjoint pools:

  * **train**   — the only pool the prompt may be iterated against.
  * **holdout** — read once, for the final reported metrics. Never tuned on.

Keeping the split *in the data* (not in the harness) makes the discipline auditable: you
can see at a glance which repos are burned for iteration and which are held in reserve.

Every label carries a **required** ``reason`` — a one-line falsifiable justification drawn
from the commits. A label without a reason is not a label, it is a guess, so loading fails
loud rather than silently scoring against unjustified ground truth.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, field_validator

VALID_LABELS = ("strong", "weak")


class LabelValidationError(Exception):
    """A label file is malformed: bad/missing label, or a missing/blank reason."""


class LabeledRepo(BaseModel):
    """One frozen label: a repo+author known to be strong/weak on ownership.

    ``reason`` is required and must be non-blank — the falsifiable one-liner that says
    *why* this is the ground-truth verdict, in terms a skeptic could check against the
    commit history.
    """

    repo: str
    author: str
    label: str  # "strong" | "weak"
    reason: str  # REQUIRED, non-blank — the falsifiable justification

    @field_validator("label")
    @classmethod
    def _label_valid(cls, v: str) -> str:
        if v not in VALID_LABELS:
            raise ValueError(f"label must be one of {VALID_LABELS}, got {v!r}")
        return v

    @field_validator("reason")
    @classmethod
    def _reason_present(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("reason is required and must be a non-blank one-line justification")
        return v.strip()

    @property
    def label_is_strong(self) -> bool:
        return self.label == "strong"


class LabelSet(BaseModel):
    """The full labeled corpus, split into train and holdout pools."""

    train: list[LabeledRepo] = []
    holdout: list[LabeledRepo] = []

    @property
    def total(self) -> int:
        return len(self.train) + len(self.holdout)

    def all_rows(self) -> list[LabeledRepo]:
        return [*self.train, *self.holdout]


def _coerce_rows(raw: object, pool: str) -> list[LabeledRepo]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise LabelValidationError(f"'{pool}' must be a list of label entries, got {type(raw).__name__}")
    rows: list[LabeledRepo] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise LabelValidationError(f"{pool}[{i}] must be a mapping, got {type(entry).__name__}")
        try:
            rows.append(LabeledRepo.model_validate(entry))
        except Exception as e:
            # Surface which row failed and why (missing reason, bad label, ...).
            raise LabelValidationError(f"{pool}[{i}] invalid: {e}") from e
    return rows


def load_labels(path: Path) -> LabelSet:
    """Parse and validate ``eval/labels.yaml`` into a :class:`LabelSet`.

    Fails loud (``LabelValidationError``) on: a missing/blank ``reason``, an invalid
    ``label`` value, a duplicated ``(repo, author)`` across the whole corpus, or a
    ``(repo, author)`` appearing in *both* train and holdout (which would leak the holdout
    into iteration). A row's own field errors (e.g. missing reason) are raised too.
    """
    doc = yaml.safe_load(Path(path).read_text()) or {}
    if not isinstance(doc, dict):
        raise LabelValidationError("labels file must be a mapping with 'train' / 'holdout' keys")

    # Reject the legacy flat `labels:` shape explicitly rather than silently ignoring it.
    if "labels" in doc and "train" not in doc and "holdout" not in doc:
        raise LabelValidationError(
            "labels file uses the old flat 'labels:' shape; split it into 'train:' and 'holdout:'"
        )

    train = _coerce_rows(doc.get("train"), "train")
    holdout = _coerce_rows(doc.get("holdout"), "holdout")

    _check_no_overlap(train, holdout)
    return LabelSet(train=train, holdout=holdout)


def _check_no_overlap(train: list[LabeledRepo], holdout: list[LabeledRepo]) -> None:
    def key(r: LabeledRepo) -> tuple[str, str]:
        return (r.repo, r.author)

    train_keys = {key(r) for r in train}
    holdout_keys = {key(r) for r in holdout}

    leaked = train_keys & holdout_keys
    if leaked:
        raise LabelValidationError(
            f"{sorted(leaked)} appear in BOTH train and holdout — that leaks the holdout"
        )

    for pool_name, rows in (("train", train), ("holdout", holdout)):
        seen: set[tuple[str, str]] = set()
        for r in rows:
            k = key(r)
            if k in seen:
                raise LabelValidationError(f"duplicate (repo, author) in {pool_name}: {k}")
            seen.add(k)
