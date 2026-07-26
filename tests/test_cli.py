"""CLI smoke tests — the thin adapter over the library, exercised offline.

No LLM, no network, no API key. The `profile` command's judge path is covered by
tests/test_l4_judge.py against mock providers; here we check the wiring and the failure
messages a user actually sees.
"""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from cli import app
from tests.fixtures import logs, repos

runner = CliRunner()
SUBJECT = "alice@example.com"


def test_facts_runs_without_any_provider(tmp_path: Path) -> None:
    """L1 is inspectable on its own — no API key, no network beyond git."""
    repo = tmp_path / "repo"
    repos.healthy(repo)

    result = runner.invoke(app, ["facts", str(repo), "--author", SUBJECT])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["n_commits_by_subject"] == 12
    assert {f["key"] for f in payload["facts"]} == {
        "ownership_loop",
        "revert_rate",
        "test_accompanies_fix",
        "followup_latency",
        "commit_scoping",
    }


def test_facts_warns_when_the_author_is_absent(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repos.healthy(repo)

    result = runner.invoke(app, ["facts", str(repo), "--author", "nobody@example.com"])

    assert result.exit_code == 0
    assert "no commits by" in result.output


def test_facts_accepts_aliases(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repos.aliased(repo)

    without = runner.invoke(app, ["facts", str(repo), "--author", SUBJECT])
    with_alias = runner.invoke(
        app, ["facts", str(repo), "--author", SUBJECT, "--alias", "alice@personal.dev"]
    )

    assert json.loads(with_alias.stdout)["n_commits_by_subject"] == (
        json.loads(without.stdout)["n_commits_by_subject"] + 1
    )


def test_sessions_dry_run_shows_the_payload_and_exits(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    logs.write_session(log_dir / "s.jsonl", logs.healthy_session())

    result = runner.invoke(app, ["sessions", "--log-dir", str(log_dir), "--dry-run"])

    assert result.exit_code == 0
    assert "This is exactly what will be uploaded" in result.output
    assert "Read locally and NOT uploaded" in result.output


def test_sessions_abort_uploads_nothing(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    logs.write_session(log_dir / "s.jsonl", logs.healthy_session())
    out = tmp_path / "payload.json"

    result = runner.invoke(
        app, ["sessions", "--log-dir", str(log_dir), "--out", str(out)], input="n\n"
    )

    assert result.exit_code == 1
    assert "aborted" in result.output
    assert not out.exists()


def test_sessions_degrades_without_logs(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["sessions", "--log-dir", str(tmp_path / "nothing"), "--dry-run"]
    )

    assert result.exit_code == 0
    assert "DEGRADED" in result.output


def test_eval_refuses_the_empty_shipped_holdout() -> None:
    """The shipped label file is empty, and the harness says so rather than printing 0/0."""
    result = runner.invoke(app, ["eval"])

    assert result.exit_code == 1
    assert "holdout is empty" in result.output


def test_eval_rejects_a_malformed_label_file(tmp_path: Path) -> None:
    bad = tmp_path / "labels.yaml"
    bad.write_text("just: a string\n")

    result = runner.invoke(app, ["eval", "--labels", str(bad)])

    assert result.exit_code == 2
    assert "label validation failed" in result.output


def test_profile_fails_loud_without_a_provider(tmp_path: Path, monkeypatch) -> None:
    """No credentials: say so, and point at the layer that still works."""
    repo = tmp_path / "repo"
    repos.healthy(repo)
    monkeypatch.setattr(
        "vouch.l4.providers.AnthropicProvider.is_available", lambda _self: False
    )

    result = runner.invoke(app, ["profile", str(repo), "--author", SUBJECT])

    assert result.exit_code == 1
    assert "judge failed" in result.output
    assert "vouch facts" in result.output
