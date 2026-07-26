"""Human-readable rendering of an :class:`~vouch.eval.EvalReport`.

Every metric is printed with its n. Warnings are printed first and loud — a directional
number the reader mistakes for evidence is worse than no number. Calibration is shown as
``insufficient_n``, never as a curve and never as "calibrated".
"""
from __future__ import annotations

from vouch.eval import EvalReport, Metrics


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def _num(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def _metrics_lines(m: Metrics) -> list[str]:
    lines = [
        "METRICS (n printed alongside every number — read them):",
        f"  labeled in split:   {m.n_labeled}",
        f"  scored (accepted):  {m.n_scored}   <- metric denominator",
        f"  judge failures:     {m.n_judge_failed}   (malformed JSON / hallucinated SHA)",
        f"  unsupported:        {m.n_unsupported}   (inflated, no evidence — rejected)",
        f"  no evidence:        {m.n_no_evidence}   (no commits by subject)",
        "",
        f"  (a) agreement:      {_pct(m.agreement)}   (n={m.n_scored}: "
        f"{m.n_correct} correct / {m.n_incorrect} incorrect)",
        "  (b) confidence separation:",
        f"        mean confidence when correct:    {_num(m.mean_confidence_correct)} "
        f"(n={m.n_correct})",
        f"        mean confidence when incorrect:  {_num(m.mean_confidence_incorrect)} "
        f"(n={m.n_incorrect})",
        f"        separation (correct - incorrect): {_num(m.confidence_separation)}",
        "",
        f"  calibration:        {m.calibration_status}   "
        f"(need n>={m.calibration_threshold} scored; NOT a reliability curve, NOT 'calibrated')",
    ]
    return lines


def format_report(report: EvalReport) -> str:
    """Render an :class:`EvalReport` to a terminal-friendly string."""
    out: list[str] = []
    out.append("=" * 72)
    out.append(f"vouch eval — split={report.split}  prompt={report.prompt_version}")
    out.append(
        f"strong-threshold={report.verdict_strong_threshold}  "
        f"total-labeled-corpus={report.total_labeled}"
    )
    out.append(f"judge cache: {report.cache_hits} hit / {report.cache_misses} miss")
    out.append("=" * 72)

    if report.warnings:
        out.append("")
        out.append("!!! WARNINGS " + "!" * 59)
        for w in report.warnings:
            out.append(f"  ! {w}")
        out.append("!" * 72)

    out.append("")
    out.extend(_metrics_lines(report.metrics))

    out.append("")
    out.append("PER-REPO:")
    for r in report.results:
        mark = {"scored": "✓" if r.correct else "✗", "judge_failed": "!",
                "unsupported": "✗", "no_evidence": "·"}.get(r.outcome, "?")
        cache_tag = " [cached]" if r.from_cache else ""
        head = f"  {mark} [{r.outcome}] {r.repo} <{r.author}>  label={r.label}{cache_tag}"
        out.append(head)
        if r.outcome == "scored":
            out.append(
                f"        predicted={r.predicted} score={_num(r.score)} "
                f"confidence={_num(r.confidence)} via {r.judge_model}"
            )
        elif r.detail:
            out.append(f"        {r.detail}")
    out.append("")
    return "\n".join(out)
