"""CLI wiring tests via typer's CliRunner. The judge is monkeypatched so no LLM/network
is touched; --evidence-only exercises the fully-deterministic path with no patching."""
import json
from datetime import date
from pathlib import Path

from typer.testing import CliRunner

import cli as cli_module
from tests.fixtures.builder import ALICE, Step, build_repo
from vouch.schemas import Verdict

runner = CliRunner()


def _fixture_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "r"
    build_repo(
        repo,
        [
            Step(ALICE, "2024-01-01T10:00:00", "add calc", {"calc.py": "def f():\n    return 1\n"}),
            Step(ALICE, "2024-02-10T10:00:00", "fix calc bug", {"calc.py": "def f():\n    return 2\n"}),
        ],
    )
    return repo


def test_evidence_only_runs_without_provider(tmp_path: Path, monkeypatch):
    repo = _fixture_repo(tmp_path)
    monkeypatch.chdir(tmp_path)  # cache lands in tmp
    result = runner.invoke(
        cli_module.app,
        ["run", str(repo), "--author", "alice@example.com", "--evidence-only"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["subject"] == "alice@example.com"
    assert {s["key"] for s in payload["signals"]} == {
        "returned_to_own_code", "fixed_own_bug", "tests_accompany_fixes",
        "revert_recovery", "commit_atomicity",
    }


def test_full_run_with_monkeypatched_judge(tmp_path: Path, monkeypatch):
    repo = _fixture_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    def fake_judge(bundle, config=None):
        sha = next(iter(bundle.commit_index))  # cite a real, grounded sha
        v = Verdict(dimension="ownership", score=0.75, confidence=0.5,
                    freshness=date(2024, 2, 10), rationale=f"self-fix {sha[:8]}",
                    cited_evidence=[sha])
        return v, "stub:test-model"

    monkeypatch.setattr(cli_module, "judge", fake_judge)
    out_path = tmp_path / "report.json"
    result = runner.invoke(
        cli_module.app,
        ["run", str(repo), "--author", "alice@example.com", "--out", str(out_path), "--markdown"],
    )
    assert result.exit_code == 0, result.output
    report = json.loads(out_path.read_text())
    assert report["judge_model"] == "stub:test-model"
    assert report["prompt_version"] == "ownership-v0"
    assert report["verdict"]["score"] == 0.75
    assert "# Ownership report" in result.stdout  # markdown printed


def test_judge_failure_exits_nonzero(tmp_path: Path, monkeypatch):
    repo = _fixture_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    from vouch.judge import JudgeError

    def boom(bundle, config=None):
        raise JudgeError("no judge provider available")

    monkeypatch.setattr(cli_module, "judge", boom)
    result = runner.invoke(cli_module.app, ["run", str(repo), "--author", "alice@example.com"])
    assert result.exit_code == 1
    assert "judge failed" in result.output
