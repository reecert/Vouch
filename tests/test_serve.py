"""The hosted path: a queued job becomes a document, or a sentence saying why it did not.

Three properties matter more than the plumbing, and each has a discriminating negative here.

**A claim is atomic.** The queue is one table read by two processes, so the test that counts
is that a second claim cannot see a row the first one took.

**A server-side profile is git-only.** Not by configuration — by the fact that a server
cannot read `~/.claude/projects`. The negative case is a profile that claims corroboration
it could not have collected.

**A failure is a sentence, not a traceback.** The reason string is rendered in a browser, so
it is scanned with the same canary floor the shared documents are.

Everything runs offline: a fixture repo cloned from a local `VOUCH_GIT_BASE`, and a bound
mock judge. No network, no API key, no GitHub.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from tests.conftest import assert_no_machine_locals
from tests.fixtures import repos
from vouch.ingest import ingest
from vouch.l1.extract import extract_facts
from vouch.l4.diffs import extract_diff
from vouch.l4.grounding import build_allowlist
from vouch.l4.judge import JudgeError
from vouch.l4.mock import MockJudgeProvider, MockMode
from vouch.l4.sampling import select_commits
from vouch.serve import worker as worker_mod
from vouch.serve.db import GITHUB_FULL_NAME, JobStatus, claim_next_job, connect, new_id, now
from vouch.serve.worker import WorkerNotReady, run_job, serve_forever

WEB = Path(__file__).resolve().parents[1] / "web"
SUBJECT = "alice@example.com"
FULL_NAME = "acme/api"


@pytest.fixture
def forge(tmp_path, monkeypatch):
    """A local stand-in for github.com: `VOUCH_GIT_BASE` + `owner/repo` resolves to a fixture."""
    root = tmp_path / "forge"
    repo = root / FULL_NAME
    repo.parent.mkdir(parents=True)
    repos.healthy(repo)
    monkeypatch.setenv("VOUCH_GIT_BASE", f"{root}/")
    monkeypatch.chdir(tmp_path)
    return repo


@pytest.fixture
def judge(forge):
    provider = MockJudgeProvider(MockMode.HONEST)
    snapshot = ingest(str(forge))
    facts = extract_facts(snapshot, SUBJECT, forge)
    sample = select_commits(snapshot.commits, facts)
    provider.bind(build_allowlist(facts, [extract_diff(forge, c) for c in sample.commits]))
    return provider


def enqueue(conn, full_name=FULL_NAME, email=SUBJECT) -> str:
    conn.execute(
        "INSERT INTO users (gh_id, login, created_at) VALUES (1, 'alice', ?)", (now(),)
    )
    job_id = new_id()
    conn.execute(
        "INSERT INTO jobs (id, user_id, full_name, author_email, status, created_at)"
        " VALUES (?, 1, ?, ?, ?, ?)",
        (job_id, full_name, email, JobStatus.QUEUED, now()),
    )
    return job_id


class TestTheQueue:
    def test_a_claimed_job_is_not_claimable_again(self, tmp_path) -> None:
        """Two workers on one host is the deployment; a double-run is a double-charge."""
        with connect(tmp_path / "db") as conn:
            enqueue(conn)
            assert claim_next_job(conn) is not None
            assert claim_next_job(conn) is None

    def test_jobs_are_claimed_oldest_first(self, tmp_path) -> None:
        with connect(tmp_path / "db") as conn:
            enqueue(conn)
            conn.execute(
                "INSERT INTO jobs (id, user_id, full_name, author_email, status, created_at)"
                " VALUES ('later', 1, ?, ?, ?, '2099-01-01T00:00:00+00:00')",
                (FULL_NAME, SUBJECT, JobStatus.QUEUED),
            )
            first = claim_next_job(conn)
            assert first is not None and first["id"] != "later"


class TestTheRepoNameIsNotAnAddress:
    @pytest.mark.parametrize(
        "hostile",
        [
            "../../etc/passwd",
            "/etc/passwd",
            "file:///etc/passwd",
            "git@github.com:acme/api",
            "--upload-pack=touch /tmp/pwned",
            "acme/api --config=core.sshCommand=x",
            "https://github.com/acme/api",
            "acme",
            "acme/api/extra",
        ],
    )
    def test_a_hostile_name_is_rejected(self, hostile: str) -> None:
        """The API builds the URL from this, so anything that is not a name must not match."""
        assert not GITHUB_FULL_NAME.match(hostile)

    def test_a_real_name_is_accepted(self) -> None:
        for good in ("acme/api", "torvalds/linux", "a/b", "Org.Name/repo-1_2"):
            assert GITHUB_FULL_NAME.match(good)

    def test_the_two_languages_validate_identically(self) -> None:
        """The web app rejects at the door and the worker builds the URL — same pattern, twice.

        A copy that drifts is worse than no copy: the browser would accept a string the
        worker then hands to `git clone` under a rule nobody re-read.
        """
        ts = (WEB / "app" / "api" / "jobs" / "route.ts").read_text()
        declared = re.search(r"const FULL_NAME = /\^(.+)\$/;", ts)

        assert declared, "app/api/jobs/route.ts no longer declares FULL_NAME as a literal"
        # TypeScript escapes the `/` that Python's pattern leaves bare; nothing else may differ.
        assert declared.group(1).replace(r"\/", "/") == GITHUB_FULL_NAME.pattern.strip("^$")


class TestRunningAJob:
    def test_a_job_produces_a_profile_on_disk(self, tmp_path, forge, judge) -> None:
        profile_dir = tmp_path / "profiles"

        profile_id, reason = run_job(FULL_NAME, SUBJECT, profile_dir, judge)

        assert reason == ""
        assert (profile_dir / f"{profile_id}.json").is_file()

    def test_the_profile_is_git_only(self, tmp_path, forge, judge) -> None:
        """A server cannot read `~/.claude/projects`; the document must say so, not omit it."""
        profile_dir = tmp_path / "profiles"
        profile_id, _ = run_job(FULL_NAME, SUBJECT, profile_dir, judge)
        doc = json.loads((profile_dir / f"{profile_id}.json").read_text())

        assert doc["evidence_inspected"]["session_telemetry"] is False
        assert doc["corroboration"]["ran"] is False
        assert any(f["verdict"] == "not_collected" for f in doc["findings"])

    def test_the_document_carries_no_machine_local_data(self, tmp_path, forge, judge) -> None:
        profile_dir = tmp_path / "profiles"
        profile_id, _ = run_job(FULL_NAME, SUBJECT, profile_dir, judge)

        assert_no_machine_locals((profile_dir / f"{profile_id}.json").read_text())

    def test_a_wrong_address_fails_with_an_answerable_reason(self, tmp_path, forge, judge) -> None:
        """The commonest real failure: the login email is not the commit email."""
        profile_id, reason = run_job(FULL_NAME, "nobody@example.com", tmp_path / "p", judge)

        assert profile_id == ""
        assert "nobody@example.com" in reason
        assert not (tmp_path / "p").exists(), "a job with no evidence still wrote a document"


class TestFailuresAreReadable:
    @pytest.mark.parametrize(
        "exc",
        [
            subprocess.CalledProcessError(128, ["git", "clone"], stderr="/Users/someone/x"),
            JudgeError("no grounded claim for /Users/someone/Projects/secret"),
            RuntimeError("/Users/someone/.ssh/id_rsa"),
        ],
    )
    def test_a_reason_never_quotes_the_exception(self, exc: Exception) -> None:
        """`reason` is rendered in a browser and a traceback quotes absolute paths."""
        reason = worker_mod._reason(exc)

        assert "/Users/" not in reason
        assert reason.endswith(".")
        assert_no_machine_locals(reason)

    def test_a_failing_job_is_recorded_rather_than_killing_the_worker(
        self, tmp_path, forge, judge, monkeypatch
    ) -> None:
        """One bad repo must not stop the queue: the next job still runs."""
        def boom(*_args, **_kwargs):
            raise subprocess.CalledProcessError(128, ["git", "clone"])

        monkeypatch.setattr(worker_mod, "run_job", boom)
        monkeypatch.setattr(worker_mod, "build_default_provider", lambda: judge)

        db = tmp_path / "db"
        with connect(db) as conn:
            job_id = enqueue(conn)

        assert serve_forever(db, tmp_path / "profiles", once=True) == 1

        with connect(db) as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        assert row["status"] == JobStatus.FAILED
        assert "cloned" in row["reason"]
        assert row["finished_at"]


class TestServeForever:
    def test_it_drains_the_queue_and_records_the_profile(self, tmp_path, forge, judge, monkeypatch) -> None:
        monkeypatch.setattr(worker_mod, "build_default_provider", lambda: judge)
        db = tmp_path / "db"
        with connect(db) as conn:
            job_id = enqueue(conn)

        assert serve_forever(db, tmp_path / "profiles", once=True) == 1

        with connect(db) as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        assert row["status"] == JobStatus.DONE
        assert re.fullmatch(r"[a-f0-9]{16}", row["profile_id"])
        assert (tmp_path / "profiles" / f"{row['profile_id']}.json").is_file()

    def test_an_empty_queue_is_not_an_error(self, tmp_path, judge, monkeypatch) -> None:
        monkeypatch.setattr(worker_mod, "build_default_provider", lambda: judge)
        assert serve_forever(tmp_path / "db", tmp_path / "profiles", once=True) == 0

    def test_an_unavailable_judge_stops_before_a_job_is_claimed(
        self, tmp_path, forge, monkeypatch
    ) -> None:
        """A missing key must not drain the queue into failures that blame the repository."""
        class Unavailable:
            name = "anthropic"
            def is_available(self) -> bool:
                return False

        monkeypatch.setattr(worker_mod, "build_default_provider", Unavailable)

        db = tmp_path / "db"
        with connect(db) as conn:
            job_id = enqueue(conn)

        with pytest.raises(WorkerNotReady):
            serve_forever(db, tmp_path / "profiles", once=True)

        with connect(db) as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        assert row["status"] == JobStatus.QUEUED
