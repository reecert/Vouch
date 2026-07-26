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
"""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from vouch.l4.schema import DimensionKey, Verdict

__all__ = [
    "LabelValidationError",
    "DimensionLabel",
    "LabelSet",
    "load_labels",
]


class LabelValidationError(Exception):
    """A label file is malformed, or the holdout has leaked into train."""


class DimensionLabel(BaseModel):
    """One frozen judgement: what a careful human says about this dimension, and why."""

    model_config = ConfigDict(extra="forbid")

    repo: str
    author: str
    dimension: DimensionKey
    verdict: Verdict
    reason: str  # REQUIRED, non-blank
    aliases: list[str] = Field(default_factory=list)

    @field_validator("reason")
    @classmethod
    def _reason_present(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError(
                "reason is required and must be a non-blank, falsifiable one-liner"
            )
        return v.strip()

    @property
    def key(self) -> tuple[str, str, DimensionKey]:
        return (self.repo, self.author, self.dimension)


class LabelSet(BaseModel):
    """The two disjoint pools."""

    model_config = ConfigDict(extra="forbid")

    train: list[DimensionLabel] = Field(default_factory=list)
    holdout: list[DimensionLabel] = Field(default_factory=list)

    def all_rows(self) -> list[DimensionLabel]:
        return [*self.train, *self.holdout]

    @property
    def total(self) -> int:
        return len(self.train) + len(self.holdout)


def load_labels(path: Path) -> LabelSet:
    """Load and validate a label file. Raises rather than silently accepting a bad one."""
    if not path.is_file():
        raise FileNotFoundError(f"no label file at {path}")

    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise LabelValidationError(f"{path}: not valid YAML: {e}") from e

    if not isinstance(raw, dict) or not {"train", "holdout"} <= set(raw):
        raise LabelValidationError(
            f"{path}: expected top-level 'train:' and 'holdout:' pools"
        )

    try:
        labels = LabelSet.model_validate(
            {"train": raw.get("train") or [], "holdout": raw.get("holdout") or []}
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

    return labels
