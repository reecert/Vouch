"""vouch CLI — a thin typer adapter over the library. All logic lives in ``vouch/``."""
from __future__ import annotations

from pathlib import Path

import typer

from vouch.eval import (
    EvalError,
    LabelValidationError,
    format_report,
    load_labels,
    run_eval,
)
from vouch.ingest import ingest, resolve_repo
from vouch.l1.extract import extract_facts
from vouch.l2.metrics import derive_metrics
from vouch.l2.parser import parse_log_dir
from vouch.l2.payload import SessionMetrics
from vouch.l2.preview import render_payload, render_preview
from vouch.l3.join import join
from vouch.l4.judge import JudgeError, judge_profile
from vouch.l4.prompt import PROMPT_VERSION
from vouch.l4.providers import build_default_provider
from vouch.l5.profile import build_profile

app = typer.Typer(help="vouch — evidence-backed capability profiles from real commits.")

# Module-level singletons: typer wants the option object as the default, and building it
# inline would be a function call in an argument default.
_ALIAS = typer.Option(
    [], "--alias", help="Additional address this person commits under. Repeatable."
)


@app.command()
def facts(
    repo_url: str = typer.Argument(..., help="Public git repo URL (or local path)."),
    author: str = typer.Option(..., "--author", help="Author email to evaluate."),
    alias: list[str] = _ALIAS,
    out: str | None = typer.Option(None, "--out", help="Write the JSON to this path."),
) -> None:
    """Run L1 only: the deterministic facts and confounds. No LLM, no network beyond git.

    This is the layer to inspect when a profile says something surprising — everything
    downstream is built on it, and it is byte-reproducible.
    """
    repo_path = resolve_repo(repo_url)
    snapshot = ingest(repo_url)
    result = extract_facts(snapshot, author, repo_path, aliases=list(alias))

    if result.n_commits_by_subject == 0:
        typer.echo(f"warning: no commits by {author} in {repo_url}", err=True)

    payload = result.model_dump_json(indent=2)
    if out:
        Path(out).write_text(payload)
        typer.echo(f"wrote {out}", err=True)
    else:
        typer.echo(payload)


@app.command()
def profile(
    repo_url: str = typer.Argument(..., help="Public git repo URL (or local path)."),
    author: str = typer.Option(..., "--author", help="Author email to evaluate."),
    alias: list[str] = _ALIAS,
    sessions_file: str | None = typer.Option(
        None,
        "--sessions",
        help="Session metrics JSON from `vouch sessions`. Omit to run git-only.",
    ),
    log_dir: str | None = typer.Option(
        None,
        "--log-dir",
        help="Correlate against session logs in this directory (local join, L3).",
    ),
    out: str | None = typer.Option(None, "--out", help="Write the JSON to this path."),
    web_dir: str | None = typer.Option(
        None,
        "--web-dir",
        help="Also write the snapshot into a viewer's data directory (web/data/profiles).",
    ),
) -> None:
    """Run the full pipeline: facts -> corroboration -> diff-level judgment -> profile.

    Emits the shareable profile document. Dimensions that depend on session telemetry
    report ``not_assessed`` when it is absent, rather than being guessed at.
    """
    repo_path = resolve_repo(repo_url)
    snapshot = ingest(repo_url)
    facts_result = extract_facts(snapshot, author, repo_path, aliases=list(alias))

    metrics: SessionMetrics | None = None
    if sessions_file:
        metrics = SessionMetrics.model_validate_json(Path(sessions_file).read_text())

    corroboration = None
    if log_dir:
        parsed = parse_log_dir(Path(log_dir))
        corroboration = join(snapshot.commits, parsed.sessions, repo_path)

    try:
        result = judge_profile(
            build_default_provider(),
            facts_result,
            repo_path,
            snapshot.commits,
            metrics=metrics,
            corroboration=corroboration,
        )
    except JudgeError as e:
        typer.echo(f"judge failed: {e}", err=True)
        typer.echo("(run `vouch facts` to inspect the deterministic layer)", err=True)
        raise typer.Exit(1) from e

    profile_doc = build_profile(facts_result, result, metrics, corroboration)
    payload = profile_doc.model_dump_json(indent=2)

    if web_dir:
        target = Path(web_dir) / f"{profile_doc.profile_id}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload)
        typer.echo(f"wrote {target}", err=True)

    if out:
        Path(out).write_text(payload)
        typer.echo(f"wrote {out}", err=True)
    elif not web_dir:
        typer.echo(payload)

    typer.echo(f"share link: {profile_doc.share_path}", err=True)


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
        "eval/labels.yaml", "--labels", help="Frozen train/holdout label set."
    ),
    split: str = typer.Option(
        "holdout",
        "--split",
        help="Which pool to score: 'train' (iterate), 'holdout' (report), or 'all'.",
    ),
) -> None:
    """Score the judge's dimension verdicts against hand-labelled ground truth.

    Refuses an empty holdout and warns loudly when the corpus is too small to be evidence.
    Reports overclaims separately from underclaims: concluding where a human declined is
    the failure this product exists to avoid, and an aggregate agreement figure hides it.
    """
    try:
        labels = load_labels(Path(labels_path))
    except (LabelValidationError, FileNotFoundError) as e:
        typer.echo(f"label validation failed: {e}", err=True)
        raise typer.Exit(2) from e

    def judge_one(label):
        repo_path = resolve_repo(label.repo)
        snapshot = ingest(label.repo)
        facts_result = extract_facts(
            snapshot, label.author, repo_path, aliases=label.aliases
        )
        result = judge_profile(
            build_default_provider(),
            facts_result,
            repo_path,
            snapshot.commits,
        )
        return result.finding(label.dimension)

    try:
        report = run_eval(
            labels, judge_one, split=split, prompt_version=PROMPT_VERSION
        )
    except EvalError as e:
        typer.echo(f"eval refused: {e}", err=True)
        raise typer.Exit(1) from e

    typer.echo(format_report(report))


if __name__ == "__main__":
    app()
