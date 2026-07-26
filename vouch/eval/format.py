"""Human-readable rendering of an :class:`~vouch.eval.harness.EvalReport`.

Warnings print first and loud — a directional number mistaken for evidence is worse than no
number. Every metric prints with its n. Overclaims are called out separately from
underclaims, because they are the failure that matters here and an aggregate agreement
figure hides them.
"""
from __future__ import annotations

from vouch.eval.harness import EvalMetrics, EvalReport

__all__ = ["format_report"]

_RULE = "─" * 72


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def _metric_lines(m: EvalMetrics) -> list[str]:
    return [
        "METRICS (n printed alongside every number — read them):",
        f"  labelled in split:  {m.n_labelled}",
        f"  scored:             {m.n_scored}   <- the denominator for everything below",
        f"  failed to run:      {m.n_judge_failed}",
        f"  no finding:         {m.n_no_finding}",
        "",
        f"  exact agreement:    {_pct(m.exact_agreement)}   "
        f"(n={m.n_scored}: {m.n_exact} exact)",
        f"  within one band:    {_pct(m.adjacent_agreement)}   "
        f"(n={m.n_scored}: {m.n_adjacent} adjacent)",
        "",
        "  DIRECTION OF DISAGREEMENT — the number this product turns on:",
        f"    overclaimed:      {_pct(m.overclaim_rate)}   ({m.n_overclaim} row(s)) "
        "<- concluded where a human declined",
        f"    underclaimed:     {_pct(m.underclaim_rate)}   ({m.n_underclaim} row(s)) "
        "<- declined where a human concluded",
        "",
        f"  calibration:        {m.calibration_status}   "
        f"(needs n>={m.calibration_threshold} scored; not a reliability curve, "
        "and never described as 'calibrated')",
    ]


def format_report(report: EvalReport) -> str:
    lines = [_RULE, f"EVAL — split: {report.split}"]
    if report.prompt_version:
        lines.append(f"prompt: {report.prompt_version}")
    lines.append(f"labels in corpus: {report.total_labelled}")
    lines.append(_RULE)

    if report.warnings:
        lines.append("WARNINGS:")
        lines += [f"  !! {w}" for w in report.warnings]
        lines.append(_RULE)

    lines += _metric_lines(report.metrics)
    lines.append(_RULE)

    disagreements = [r for r in report.results if r.exact is False]
    if disagreements:
        lines.append("DISAGREEMENTS:")
        for row in disagreements:
            marker = f" [{row.direction}]" if row.direction else ""
            lines.append(
                f"  {row.dimension:24} expected={row.expected:22} "
                f"got={row.predicted}{marker}"
            )
        lines.append(_RULE)

    return "\n".join(lines)
