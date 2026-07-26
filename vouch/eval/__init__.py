"""eval — score L4's dimension verdicts against hand-labelled ground truth.

The crux, and still unfinished: the machinery is here, the labels are not. Until
``eval/labels.yaml`` is populated, nothing in this repository licenses a claim about the
judge's accuracy, and the harness refuses to pretend otherwise.
"""
from vouch.eval.corpus import (
    AuthorSelector,
    Corpus,
    CorpusError,
    RepoSpec,
    ResolvedAuthor,
    load_corpus,
    resolve_aliases,
    resolve_author,
)
from vouch.eval.format import format_report
from vouch.eval.harness import (
    MIN_LABELS_FOR_CALIBRATION,
    MIN_LABELS_FOR_EVIDENCE,
    EvalError,
    EvalMetrics,
    EvalReport,
    RowResult,
    run_eval,
)
from vouch.eval.labels import (
    DimensionLabel,
    LabelSet,
    LabelValidationError,
    load_labels,
)

__all__ = [
    "AuthorSelector",
    "Corpus",
    "CorpusError",
    "DimensionLabel",
    "EvalError",
    "EvalMetrics",
    "EvalReport",
    "LabelSet",
    "LabelValidationError",
    "MIN_LABELS_FOR_CALIBRATION",
    "MIN_LABELS_FOR_EVIDENCE",
    "RepoSpec",
    "ResolvedAuthor",
    "RowResult",
    "format_report",
    "load_corpus",
    "load_labels",
    "resolve_aliases",
    "resolve_author",
    "run_eval",
]
