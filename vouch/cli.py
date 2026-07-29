"""vouch CLI — a thin typer adapter over the library. All logic lives in ``vouch/``."""
from __future__ import annotations

from pathlib import Path

import typer
from pydantic import ValidationError

from vouch.eval import (
    EvalError,
    LabelValidationError,
    format_report,
    load_labels,
    run_eval,
)
from vouch.eval.corpus import (
    CorpusError,
    load_corpus,
    resolve_aliases,
    resolve_author,
)
from vouch.eval.labeling import (
    append_label,
    build_task,
    current_provenance,
    pending_tasks,
    render_task,
)
from vouch.eval.labels import (
    NO_MEASURE,
    DimensionLabel,
    LabelSet,
    permitted_measures,
)
from vouch.ingest import DEFAULT_CACHE_DIR, ingest, resolve_repo
from vouch.l1.cache import cached_extract
from vouch.l1.extract import extract_facts
from vouch.l2.metrics import derive_metrics
from vouch.l2.parser import default_log_dir, parse_snapshot
from vouch.l2.payload import MetricScope, SessionMetrics
from vouch.l2.preview import render_payload, render_preview
from vouch.l2.snapshot import open_snapshot, snapshot_sessions
from vouch.l3.repo_identity import (
    discover_candidate_roots,
    history_paths,
    resolve_identity,
)
from vouch.l4.judge import JudgeError, judge_profile
from vouch.l4.prompt import PROMPT_VERSION
from vouch.l4.providers import build_default_provider
from vouch.l4.schema import Verdict
from vouch.pipeline import run_profile
from vouch.serve.worker import serve_forever

app = typer.Typer(help="vouch — evidence-backed capability profiles from real commits.")

# Module-level so the shared options are not function calls in an argument default.
_ALIAS = typer.Option(
    [], "--alias", help="Additional address this person commits under. Repeatable."
)
_REFRESH = typer.Option(
    False,
    "--refresh",
    help="Recompute L1 instead of reusing the cache keyed on repo + HEAD + extractor version.",
)
_HISTORICAL_ROOT = typer.Option(
    [],
    "--historical-root",
    help=(
        "A previous absolute path of this repo, so sessions recorded before a move still "
        "correlate. Repeatable. Adds to .vouch/identity.yaml rather than replacing it; "
        "run `vouch identity --propose` to see candidates."
    ),
)


@app.command()
def facts(
    repo_url: str = typer.Argument(..., help="Public git repo URL (or local path)."),
    author: str = typer.Option(..., "--author", help="Author email to evaluate."),
    alias: list[str] = _ALIAS,
    refresh: bool = _REFRESH,
    out: str | None = typer.Option(None, "--out", help="Write the JSON to this path."),
) -> None:
    """Run L1 only: the deterministic facts and confounds. No LLM, no network beyond git.

    This is the layer to inspect when a profile says something surprising — everything
    downstream is built on it, and it is byte-reproducible.
    """
    repo_path = resolve_repo(repo_url)
    snapshot = ingest(repo_url)
    result, was_cached = cached_extract(
        repo_url,
        snapshot.head_sha,
        author,
        lambda: extract_facts(snapshot, author, repo_path, aliases=list(alias)),
        aliases=list(alias),
        refresh=refresh,
    )
    if was_cached:
        typer.echo("(from the L1 cache; pass --refresh to recompute)", err=True)

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
    historical_root: list[str] = _HISTORICAL_ROOT,
    as_of: str | None = typer.Option(
        None,
        "--as-of",
        help=(
            "Re-read an earlier session snapshot by digest instead of taking a new one. "
            "Two runs at the same --as-of produce a byte-identical profile."
        ),
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
    report ``not_collected`` when it is absent, rather than being guessed at.
    """
    metrics: SessionMetrics | None = None
    if sessions_file:
        metrics = SessionMetrics.model_validate_json(Path(sessions_file).read_text())
        if metrics.scope is not MetricScope.REPO:
            typer.echo(
                f"warning: {sessions_file} was measured at {metrics.scope.value} scope; "
                "dimensions needing repo-scoped telemetry will be out_of_scope",
                err=True,
            )

    frozen = None
    if log_dir or as_of:
        # A frozen copy, never the live directory this CLI's own session is appending to.
        frozen = (
            open_snapshot(as_of, DEFAULT_CACHE_DIR)
            if as_of
            else snapshot_sessions(
                Path(log_dir) if log_dir else default_log_dir(), DEFAULT_CACHE_DIR
            )
        )
        typer.echo(
            f"session snapshot: {frozen.digest} "
            f"({frozen.n_files} file(s), as of {frozen.as_of})",
            err=True,
        )

    try:
        profile_doc = run_profile(
            repo_url,
            author,
            provider=build_default_provider(),
            aliases=list(alias),
            historical_roots=list(historical_root),
            frozen=frozen,
            metrics=metrics,
        )
    except JudgeError as e:
        typer.echo(f"judge failed: {e}", err=True)
        typer.echo("(run `vouch facts` to inspect the deterministic layer)", err=True)
        raise typer.Exit(1) from e

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
    source = Path(log_dir) if log_dir else default_log_dir()
    result = parse_snapshot(snapshot_sessions(source, DEFAULT_CACHE_DIR))
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


@app.command("identity")
def identity_(
    repo_url: str = typer.Argument(..., help="Public git repo URL (or local path)."),
    log_dir: str | None = typer.Option(
        None, "--log-dir", help="Session log root (default: ~/.claude/projects)."
    ),
    propose: bool = typer.Option(
        False, "--propose", help="Scan the logs for directories this repo may have moved from."
    ),
) -> None:
    """Show which filesystem paths count as this repo, and what else might have.

    ``--propose`` reads the session logs and reports directories whose files git recognises
    from this history — the signature of a repo that was renamed or moved. **It proposes
    only.** A fork, a template, or a copy taken before the rename would score the same way,
    and promoting a guess to evidence is the failure the join exists to avoid. Accept a
    proposal by writing it into `.vouch/identity.yaml`, where it becomes a declaration the
    resolver checks against git history path by path.
    """
    repo_path = resolve_repo(repo_url)
    identity = resolve_identity(repo_path)

    typer.echo(f"canonical root : {identity.canonical_root}")
    typer.echo(
        f"filesystem     : {'case-insensitive' if identity.case_insensitive else 'case-sensitive'}"
    )
    for root in identity.historical_display or ("(none declared)",):
        typer.echo(f"historical     : {root}")

    if not propose:
        return

    source = Path(log_dir) if log_dir else default_log_dir()
    parsed = parse_snapshot(snapshot_sessions(source, DEFAULT_CACHE_DIR))
    observed = [
        (raw, event.cwd)
        for session in parsed.sessions
        for event in session.events
        for raw in event.paths
    ]
    known = history_paths(repo_path)
    candidates = discover_candidate_roots(observed, identity, known)

    typer.echo(f"\nscanned {len(parsed.sessions)} session(s), {len(observed)} edited path(s)")
    if not candidates:
        typer.echo("no candidate historical roots found")
        return

    typer.echo("\ncandidate historical roots — PROPOSALS, not conclusions:")
    for cand in candidates:
        typer.echo(
            f"  {cand.root}\n"
            f"    {cand.n_known}/{cand.n_paths} edited paths are known to this history "
            f"({cand.share_known:.0%}); e.g. {', '.join(cand.examples)}"
        )
    typer.echo(
        "\nA high share is consistent with a rename — and equally consistent with a fork "
        "or a copy.\nDeclare one in .vouch/identity.yaml only if you know the repo lived "
        "there."
    )


@app.command("label")
def label_(
    labels_path: str = typer.Option(
        "eval/labels.local.yaml",
        "--labels",
        help="Where labels are written. Defaults to the gitignored local file.",
    ),
    corpus_path: str = typer.Option(
        "eval/repos.yaml", "--corpus", help="The corpus to label."
    ),
    only: str | None = typer.Option(
        None, "--only", help="Label a single corpus row by id."
    ),
    limit: int = typer.Option(0, "--limit", help="Stop after this many tasks. 0 = no limit."),
) -> None:
    """Label the corpus by hand, blind to what the judge would say.

    Shows the deterministic evidence for one dimension of one corpus row and asks for a
    verdict. The model's answer is never rendered: shown one first, a human agrees with it
    far more often than they otherwise would, and the eval would then be measuring how
    persuasive the judge is rather than how right it is.

    Which pool a row lands in is decided before its evidence is drawn, by a hash of
    (corpus_id, dimension), so a holdout cannot be chosen after the fact.

    Writes to the gitignored `eval/labels.local.yaml` by default. Labels are one person's
    judgements about named engineers who did not ask to be judged; they stay on this
    machine.
    """
    try:
        corpus = load_corpus(Path(corpus_path))
    except CorpusError as e:
        typer.echo(f"corpus: {e}", err=True)
        raise typer.Exit(2) from e

    target = Path(labels_path)
    existing = (
        load_labels(target, known_ids={s.id for s in corpus.repos})
        if target.is_file()
        else LabelSet()
    )
    done = {(row.corpus_id, row.dimension) for row in existing.all_rows()}
    ids = [s.id for s in corpus.repos if only is None or s.id == only]
    if only is not None and not ids:
        typer.echo(f"no corpus row with id {only!r}", err=True)
        raise typer.Exit(2)

    provenance = current_provenance()
    if provenance.dirty:
        typer.echo(
            f"note: labelling against a dirty tree at {provenance.code_sha[:12]} — the "
            "recorded sha will not describe what you were shown",
            err=True,
        )
    n_done = 0

    for corpus_id, spec in pending_tasks(done, ids):
        if limit and n_done >= limit:
            break
        row = corpus.by_id(corpus_id)
        repo_path = resolve_repo(row.repo)
        snapshot = ingest(row.repo)
        subject = resolve_author(row, repo_path).email
        aliases = resolve_aliases(row, repo_path)
        facts_result, was_cached = cached_extract(
            row.repo,
            snapshot.head_sha,
            subject,
            # Bound as defaults: a late-binding closure would extract the next row on a miss.
            lambda s=snapshot, a=subject, p=repo_path, al=aliases: extract_facts(
                s, a, p, aliases=al
            ),
            aliases=aliases,
        )
        if not was_cached:
            typer.echo("(computed L1 fresh; the next pass over this row is instant)", err=True)

        # Explicitly none: the corpus is public repos, whose sessions were never on this machine.
        task = build_task(spec, corpus_id, facts_result, metrics=None)
        typer.echo(render_task(task))

        permitted = [v.value for v in task.permitted]
        while True:
            answer = typer.prompt("verdict (or 'skip', 'quit')").strip()
            if answer in ("quit", "skip") or answer in permitted:
                break
            typer.echo(f"not a verdict; expected one of {', '.join(permitted)}", err=True)
        if answer == "quit":
            break
        if answer == "skip":
            continue

        # Asked before the reason, so the reason is written about a measure already named.
        leaned_on = [NO_MEASURE]
        if not task.is_forced:
            choices = sorted(permitted_measures(spec.key))
            raw = typer.prompt(
                "leaned on (which measure carried it; comma-separated if genuinely "
                f"several) [{', '.join(choices)}]"
            )
            leaned_on = [part.strip() for part in raw.split(",") if part.strip()]

        reason = typer.prompt("reason (one falsifiable line a sceptic could check)").strip()
        try:
            # The loader's own validator, before the write, not after the half-written file.
            DimensionLabel(
                corpus_id=corpus_id,
                dimension=spec.key,
                verdict=Verdict(answer),
                reason=reason,
                leaned_on=leaned_on,
            )
        except ValidationError as e:
            typer.echo(f"not written: {e.errors()[0]['msg']}", err=True)
            continue

        try:
            append_label(
                target,
                corpus_id,
                spec.key,
                Verdict(answer),
                reason,
                leaned_on,
                task.split,
                provenance=provenance,
            )
        except Exception as e:
            typer.echo(f"not written: {e}", err=True)
            continue
        try:
            load_labels(target, known_ids={s.id for s in corpus.repos})
        except LabelValidationError as e:
            typer.echo(f"WROTE AN INVALID LABEL — fix {target} by hand: {e}", err=True)
            raise typer.Exit(1) from e
        n_done += 1

    typer.echo(f"{n_done} label(s) written to {target}", err=True)


@app.command("eval")
def eval_(
    labels_path: str = typer.Option(
        "eval/labels.yaml", "--labels", help="Frozen train/holdout label set."
    ),
    corpus_path: str = typer.Option(
        "eval/repos.yaml", "--corpus", help="The corpus a label's corpus_id resolves against."
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
        corpus = load_corpus(Path(corpus_path))
        labels = load_labels(Path(labels_path), known_ids={s.id for s in corpus.repos})
    except (LabelValidationError, CorpusError, FileNotFoundError) as e:
        typer.echo(f"label validation failed: {e}", err=True)
        raise typer.Exit(2) from e

    def judge_one(label):
        # The selector resolves to an address only here, against the clone, and in memory.
        spec = corpus.by_id(label.corpus_id)
        repo_path = resolve_repo(spec.repo)
        snapshot = ingest(spec.repo)
        subject = resolve_author(spec, repo_path).email
        aliases = resolve_aliases(spec, repo_path)
        facts_result, _ = cached_extract(
            spec.repo,
            snapshot.head_sha,
            subject,
            lambda: extract_facts(snapshot, subject, repo_path, aliases=aliases),
            aliases=aliases,
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
            labels,
            judge_one,
            split=split,
            prompt_version=PROMPT_VERSION,
            corpus_name=corpus.name,
        )
    except EvalError as e:
        typer.echo(f"eval refused: {e}", err=True)
        raise typer.Exit(1) from e

    typer.echo(format_report(report))


@app.command("worker")
def worker(
    db: str | None = typer.Option(None, "--db", help="SQLite state file (default: $VOUCH_DB)."),
    profile_dir: str | None = typer.Option(
        None, "--profile-dir", help="Where generated profiles are written (default: var/profiles)."
    ),
    once: bool = typer.Option(
        False, "--once", help="Drain the queue and exit instead of polling."
    ),
) -> None:
    """Run queued profile jobs from the web app. Git-only: a server cannot read session logs."""
    ran = serve_forever(
        Path(db) if db else None,
        Path(profile_dir) if profile_dir else None,
        once=once,
    )
    typer.echo(f"ran {ran} job(s)", err=True)


if __name__ == "__main__":
    app()
