"""vouch CLI — a thin typer adapter over the library. All logic lives in ``vouch/``."""
from __future__ import annotations

from pathlib import Path

import typer

from vouch.config import CONFIG
from vouch.eval import (
    EvalError,
    LabelValidationError,
    MockJudgeProvider,
    MockMode,
    load_labels,
    run_eval,
)
from vouch.eval.format import format_report
from vouch.extract import extract
from vouch.ingest import ingest, resolve_repo
from vouch.judge import JudgeError, build_provider_chain, judge
from vouch.judge.cache import JudgeCache
from vouch.l2.metrics import derive_metrics
from vouch.l2.parser import parse_log_dir
from vouch.l2.preview import render_payload, render_preview
from vouch.report import build_report, to_json, to_markdown

app = typer.Typer(help="vouch — evidence-backed capability reports from real commits.")


@app.command()
def run(
    repo_url: str = typer.Argument(..., help="Public git repo URL (or local path)."),
    author: str = typer.Option(..., "--author", help="Author email to evaluate."),
    markdown: bool = typer.Option(False, "--markdown", help="Also print a markdown summary."),
    out: str | None = typer.Option(None, "--out", help="Write the JSON report to this path."),
    evidence_only: bool = typer.Option(
        False,
        "--evidence-only",
        help="Skip the LLM judge; emit just the deterministic EvidenceBundle.",
    ),
) -> None:
    """Run the pipeline: ingest -> extract -> judge -> report for one author."""
    repo_path = resolve_repo(repo_url)
    snapshot = ingest(repo_url)
    bundle = extract(snapshot, author, repo_path=repo_path, config=CONFIG)

    if bundle.n_commits_by_subject == 0:
        typer.echo(f"warning: no commits by {author} in {repo_url}", err=True)

    if evidence_only:
        typer.echo(bundle.model_dump_json(indent=2))
        return

    try:
        verdict, judge_model = judge(bundle, config=CONFIG)
    except JudgeError as e:
        typer.echo(f"judge failed: {e}", err=True)
        typer.echo("(re-run with --evidence-only to inspect the deterministic signals)", err=True)
        raise typer.Exit(1) from e

    report = build_report(bundle, verdict, judge_model, CONFIG.prompt_version)
    payload = to_json(report)

    if out:
        Path(out).write_text(payload)
        typer.echo(f"wrote {out}", err=True)
    else:
        typer.echo(payload)

    if markdown:
        typer.echo("\n" + to_markdown(report))


@app.command("sessions")
def sessions(
    log_dir: str | None = typer.Option(
        None, "--log-dir", help="Session log root (default: ~/.claude/projects)."
    ),
    out: str | None = typer.Option(
        None, "--out", help="Write the confirmed payload to this path."
    ),
    yes: bool = typer.Option(
        False, "--yes", help="Skip the confirmation prompt (for scripted runs)."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show the payload and exit without confirming."
    ),
) -> None:
    """Derive session telemetry locally, show exactly what would be uploaded, and confirm.

    Raw logs and source code never leave this machine: the payload schema carries no
    free-text field, so there is nothing for them to travel in. If the log format is not
    understood, this degrades to git-only mode and emits coverage counters with no rates.
    """
    result = parse_log_dir(Path(log_dir) if log_dir else None)
    metrics = derive_metrics(result)

    typer.echo(render_preview(result, metrics))

    if dry_run:
        raise typer.Exit(0)
    if not yes and not typer.confirm("Upload these metrics?", default=False):
        typer.echo("aborted — nothing was uploaded", err=True)
        raise typer.Exit(1)

    payload = render_payload(metrics)
    if out:
        Path(out).write_text(payload)
        typer.echo(f"wrote {out}", err=True)
    else:
        typer.echo(payload)


@app.command("eval")
def eval_(
    labels_path: str = typer.Option(
        "eval/labels.yaml", "--labels", help="Path to the frozen train/holdout label set."
    ),
    split: str = typer.Option(
        "holdout",
        "--split",
        help="Which pool to score: 'train' (iterate), 'holdout' (report), or 'all'.",
    ),
    mock: bool = typer.Option(
        True,
        "--mock/--live",
        help="Offline mock judge (default) vs the real provider chain. Iterate on --mock; "
        "--live burns quota and hits the network.",
    ),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Disable the bundle-hash judge cache (forces fresh calls)."
    ),
) -> None:
    """Score the judge against the frozen labels — agreement + confidence separation.

    Refuses to report an empty holdout; warns loudly when the labeled corpus is too small
    to be evidence. Iterate on ``--split train --mock``; report the final number once with
    ``--split holdout --live``.
    """
    try:
        labels = load_labels(Path(labels_path))
    except (LabelValidationError, FileNotFoundError) as e:
        typer.echo(f"label validation failed: {e}", err=True)
        raise typer.Exit(2) from e

    if mock:
        providers = [MockJudgeProvider(MockMode.HONEST, config=CONFIG)]
    else:
        providers = build_provider_chain(CONFIG)

    cache = JudgeCache(None) if no_cache else JudgeCache()

    try:
        report = run_eval(labels, providers, split=split, cache=cache, config=CONFIG)
    except EvalError as e:
        typer.echo(f"eval refused: {e}", err=True)
        raise typer.Exit(1) from e
    except JudgeError as e:
        typer.echo(f"judge failed: {e}", err=True)
        raise typer.Exit(1) from e

    typer.echo(format_report(report))


if __name__ == "__main__":
    app()
