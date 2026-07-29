"""One run of the whole stack, from a repo address to a shareable document.

This exists because there are now two callers — the CLI a subject runs on their own
machine, and the server worker that runs a job someone queued in the browser — and the
order of the layers is not a detail either of them should own a copy of. A second
transcription of "ingest, then L1, then identity, then join, then L4, then L5" is a second
place for the two to drift, and the way they would drift is silent: a profile generated one
way would answer a question the other way could not.

**The session layers are a parameter, not a branch.** ``frozen`` is a snapshot the caller
already took, because freezing a log directory is a local act with a human behind it — the
CLI prints what it copied before anything reads it. The worker has no such argument to
pass: a server cannot see ``~/.claude/projects``, so it calls this with nothing and the
dimensions that need telemetry report ``not_collected``. Neither caller decides what that
absence *means*; L5 does, from the evidence it was handed.

**The address stops at the first line.** ``repo_url`` is resolved to a local path here and
every layer below takes the path, so no argument a caller passes can carry a home directory
into the document.
"""
from __future__ import annotations

from pathlib import Path

from vouch.ingest import ingest, resolve_repo
from vouch.l1.cache import cached_extract
from vouch.l1.extract import extract_facts
from vouch.l2.metrics import derive_metrics
from vouch.l2.parser import parse_snapshot
from vouch.l2.payload import MetricScope, SessionMetrics
from vouch.l2.snapshot import SessionSnapshot
from vouch.l3.join import join, sessions_in_repo
from vouch.l3.repo_identity import HistoricalRoot, load_identity_file, resolve_identity
from vouch.l4.judge import judge_profile
from vouch.l4.providers import JudgeProvider
from vouch.l5.profile import Profile, build_profile

__all__ = ["DEFAULT_PROFILE_DIR", "run_profile"]

#: Generated profiles land here, never in ``web/data/profiles``: that directory is tracked
#: and its bytes are pinned, so a real person's profile written beside the samples would
#: arrive in a commit.
DEFAULT_PROFILE_DIR = Path("var/profiles")


def run_profile(
    repo_url: str,
    author: str,
    *,
    provider: JudgeProvider,
    aliases: list[str] | None = None,
    historical_roots: list[str] | None = None,
    frozen: SessionSnapshot | None = None,
    metrics: SessionMetrics | None = None,
    refresh: bool = False,
) -> Profile:
    """Ingest, measure, corroborate, judge, assemble.

    ``metrics`` is a pre-measured payload (the CLI's ``--sessions``); ``frozen`` is a log
    snapshot to measure here. A ``frozen`` snapshot supersedes ``metrics``, because metrics
    derived from the snapshot being joined against are the ones the corroboration describes.

    ``provider`` has no default so each adapter names the judge it is running — which is
    also the seam a test replaces, and a default here would silently outlive the patch.
    """
    aliases = list(aliases or [])

    repo_path = resolve_repo(repo_url)
    snapshot = ingest(repo_url)
    facts, _ = cached_extract(
        repo_url,
        snapshot.head_sha,
        author,
        lambda: extract_facts(snapshot, author, repo_path, aliases=aliases),
        aliases=aliases,
        refresh=refresh,
    )

    corroboration = None
    session_digest = ""
    if frozen is not None:
        identity = resolve_identity(
            repo_path,
            declared=[
                *load_identity_file(repo_path).historical_roots,
                *(
                    HistoricalRoot(path=p, why="--historical-root")
                    for p in historical_roots or []
                ),
            ],
        )
        session_digest = frozen.digest
        parsed = parse_snapshot(frozen)
        corroboration = join(snapshot.commits, parsed.sessions, identity)
        scoped, n_out = sessions_in_repo(parsed.sessions, identity)
        metrics = derive_metrics(
            parsed.narrowed_to(scoped), scope=MetricScope.REPO, n_out_of_scope=n_out
        )

    judgment = judge_profile(
        provider,
        facts,
        repo_path,
        snapshot.commits,
        metrics=metrics,
        corroboration=corroboration,
    )
    return build_profile(
        facts, judgment, metrics, corroboration, session_digest=session_digest
    )
