"""The process that turns a queued job into a document.

It exists because the pipeline is Python and the web app is not, and because a profile
takes minutes: cloning, blaming and judging cannot happen inside a request. The queue is a
table, the worker is a loop, and a job that dies takes nothing with it — the row is still
there to read.

**A server-side profile is git-only, structurally.** ``~/.claude/projects`` is on the
subject's laptop, so no amount of server code can corroborate anything. The worker passes
no session evidence and L5 marks those dimensions ``not_collected``. The alternative — a
profile that quietly omits the distinction — would let a reader mistake "we could not look"
for "we looked and found nothing".

**Failures are reported as reasons, not as exceptions.** A traceback from ``git clone`` or
a judge quotes absolute paths, and this string is rendered in a browser. The full error
goes to the worker's own stderr; the row gets one of a fixed set of sentences.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from vouch.l4.judge import JudgeError
from vouch.l4.providers import build_default_provider
from vouch.pipeline import DEFAULT_PROFILE_DIR, run_profile
from vouch.serve.db import JobStatus, claim_next_job, connect, finish_job

__all__ = ["WorkerNotReady", "run_job", "serve_forever"]

POLL_SECONDS = 2.0


class WorkerNotReady(Exception):
    """Misconfiguration that would fail every job. Raised before any row is claimed."""


def git_base() -> str:
    """Where a validated ``owner/repo`` is cloned from. Overridable for Enterprise and tests."""
    return os.environ.get("VOUCH_GIT_BASE") or "https://github.com/"


def _reason(exc: Exception) -> str:
    """One of a fixed set of sentences. See the module docstring on why not ``str(exc)``."""
    if isinstance(exc, subprocess.CalledProcessError):
        return "The repository could not be cloned. It may be private, empty, or renamed."
    if isinstance(exc, JudgeError):
        return "The judge could not produce a grounded verdict for this history."
    return "The profile could not be generated."


def run_job(full_name: str, author_email: str, profile_dir: Path, provider) -> tuple[str, str]:
    """Run one job. Returns ``(profile_id, reason)`` — exactly one of them is non-empty.

    ``full_name`` is validated at the API boundary and the URL is built here, so a clone
    argument never originates in a browser.
    """
    profile = run_profile(f"{git_base()}{full_name}", author_email, provider=provider)
    if profile.evidence_inspected.n_commits_by_subject == 0:
        return "", (
            f"No commits by {author_email} in {full_name}. "
            "Check the address you commit under — it is often not your login email."
        )

    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / f"{profile.profile_id}.json").write_text(
        profile.model_dump_json(indent=2)
    )
    return profile.profile_id, ""


def serve_forever(
    db: Path | None = None,
    profile_dir: Path | None = None,
    *,
    once: bool = False,
    poll_seconds: float = POLL_SECONDS,
) -> int:
    """Claim and run jobs until interrupted. Returns the number of jobs run.

    ``once`` drains the queue and stops, which is what a test and a cron-style deployment
    both want; the default loop is for a long-lived process.
    """
    profile_dir = profile_dir or DEFAULT_PROFILE_DIR
    provider = build_default_provider()
    # Checked once, before claiming anything: an unavailable judge fails every job it is
    # handed, and `_reason` would report a missing key as a history the judge could not read.
    if not provider.is_available():
        raise WorkerNotReady(
            f"The {provider.name} judge is not available: install the `anthropic` extra and "
            "set ANTHROPIC_API_KEY. No jobs were claimed."
        )

    ran = 0
    with connect(db) as conn:
        while True:
            job = claim_next_job(conn)
            if job is None:
                if once:
                    return ran
                time.sleep(poll_seconds)
                continue

            print(f"job {job['id']}: {job['full_name']}", file=sys.stderr)
            try:
                profile_id, reason = run_job(
                    job["full_name"],
                    job["author_email"],
                    profile_dir,
                    provider,
                )
            except Exception as exc:  # a worker that dies on one job stops serving all of them
                print(f"job {job['id']} failed: {exc!r}", file=sys.stderr)
                finish_job(conn, job["id"], JobStatus.FAILED, reason=_reason(exc))
            else:
                finish_job(
                    conn,
                    job["id"],
                    JobStatus.DONE if profile_id else JobStatus.FAILED,
                    profile_id=profile_id,
                    reason=reason,
                )
            ran += 1
