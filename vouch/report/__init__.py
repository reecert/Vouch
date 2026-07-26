"""report — Verdict + EvidenceBundle -> CapabilityReport. Serialize JSON (+ optional md).

Records ``judge_model`` and ``prompt_version`` so any report is reproducible.
"""
from __future__ import annotations

from datetime import datetime

from vouch.schemas import CapabilityReport, EvidenceBundle, Verdict


def build_report(
    bundle: EvidenceBundle, verdict: Verdict, judge_model: str, prompt_version: str
) -> CapabilityReport:
    """Assemble the final ``CapabilityReport`` from the pipeline outputs."""
    return CapabilityReport(
        repo=bundle.repo,
        subject=bundle.subject,
        dimension=bundle.dimension,
        verdict=verdict,
        evidence=bundle.signals,
        judge_model=judge_model,
        prompt_version=prompt_version,
        generated_at=datetime.now(),
    )


def to_json(report: CapabilityReport) -> str:
    """Serialize a report to indented JSON."""
    return report.model_dump_json(indent=2)


def to_markdown(report: CapabilityReport) -> str:
    """Render a human-readable markdown summary of a report."""
    v = report.verdict
    lines = [
        f"# Ownership report — {report.subject}",
        "",
        f"- **Repo:** {report.repo}",
        f"- **Score:** {v.score:.2f}  ·  **Confidence:** {v.confidence:.2f}  ·  "
        f"**Freshness:** {v.freshness.isoformat()}",
        f"- **Judge:** {report.judge_model}  ·  **Prompt:** {report.prompt_version}",
        f"- **Generated:** {report.generated_at.isoformat(timespec='seconds')}",
        "",
        "## Rationale",
        "",
        v.rationale,
        "",
        "## Signals",
        "",
        "| signal | value | backing commits |",
        "| --- | --- | --- |",
    ]
    for s in report.evidence:
        shas = ", ".join(x[:8] for x in s.evidence) or "—"
        lines.append(f"| `{s.key}` | {s.value} | {shas} |")
    lines += [
        "",
        "## Cited evidence",
        "",
        ("- " + "\n- ".join(v.cited_evidence)) if v.cited_evidence else "_none_",
    ]
    return "\n".join(lines)
