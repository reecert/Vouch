"""CLI smoke tests — the thin adapter over the library, exercised offline.

No LLM, no network, no API key. The `profile` command's judge path is covered by
tests/test_l4_judge.py against mock providers; here we check the wiring and the failure
messages a user actually sees.
"""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from tests.conftest import assert_no_machine_locals
from tests.fixtures import logs, repos
from vouch.cli import app

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


# The labelling loop, not the harness it calls: tests/test_labeling.py covers that.


def _corpus(path: Path, repo: Path) -> Path:
    """A one-row corpus over a local fixture repo, addressing alice the way the real one does.

    `rank: 1` plus her digest — a selector, never an address, exactly as `eval/repos.yaml`
    stores it.
    """
    from vouch.eval.corpus import email_digest

    path.write_text(
        "schema_version: eval-corpus/1\n"
        "name: one-row fixture corpus (L1 only)\n"
        "repos:\n"
        "  - id: fixture\n"
        "    axis: rich\n"
        f"    repo: {repo}\n"
        "    head: HEAD\n"
        "    author:\n"
        "      by: commit_rank\n"
        "      rank: 1\n"
        f"      email_sha256: {email_digest(SUBJECT)}\n"
    )
    return path


def test_label_writes_one_answer_into_the_pool_its_split_assigned(tmp_path: Path) -> None:
    import yaml

    from vouch.eval.labeling import assign_split
    from vouch.l4.dimensions import DIMENSIONS

    repo = tmp_path / "repo"
    repos.healthy(repo)
    labels = tmp_path / "labels.local.yaml"

    result = runner.invoke(
        app,
        [
            "label",
            "--corpus", str(_corpus(tmp_path / "corpus.yaml", repo)),
            "--labels", str(labels),
            "--limit", "1",
        ],
        input=(
            "moderate\n"
            "test_accompanies_fix\n"
            "five of twelve commits pair a fix with a test in the same commit\n"
        ),
    )

    assert result.exit_code == 0, result.output
    assert "1 label(s) written" in result.output

    written = yaml.safe_load(labels.read_text())
    expected = assign_split("fixture", DIMENSIONS[0].key)
    assert len(written[expected]) == 1
    assert written["train" if expected == "holdout" else "holdout"] == []
    assert written[expected][0]["corpus_id"] == "fixture"
    # The split came off the hash, not off the answer that was given.
    assert written[expected][0]["verdict"] == "moderate"


def test_label_records_which_measure_carried_the_verdict(tmp_path: Path) -> None:
    """No rule combines a multi-fact dimension, so the corpus records what was leaned on.

    A forced answer is not asked — there was no measure — and is recorded as `none` rather
    than left blank, since a blank is what an unfilled field looks like.
    """
    import yaml

    repo = tmp_path / "repo"
    repos.healthy(repo)
    labels = tmp_path / "labels.local.yaml"

    result = runner.invoke(
        app,
        [
            "label",
            "--corpus", str(_corpus(tmp_path / "corpus.yaml", repo)),
            "--labels", str(labels),
            "--limit", "1",
        ],
        input=(
            "limited\n"
            "test_accompanies_fix, test_or_build_after_edit\n"
            "five of twelve fixes ship a test, and no session trail contradicts it\n"
        ),
    )

    assert result.exit_code == 0, result.output
    written = yaml.safe_load(labels.read_text())
    row = (written["train"] or written["holdout"])[0]
    assert row["leaned_on"] == ["test_accompanies_fix", "test_or_build_after_edit"]


def test_label_quits_without_writing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repos.healthy(repo)
    labels = tmp_path / "labels.local.yaml"

    result = runner.invoke(
        app,
        [
            "label",
            "--corpus", str(_corpus(tmp_path / "corpus.yaml", repo)),
            "--labels", str(labels),
        ],
        input="quit\n",
    )

    assert result.exit_code == 0
    assert "0 label(s) written" in result.output
    assert not labels.exists()


def test_label_refuses_an_answer_outside_the_verdict_vocabulary(tmp_path: Path) -> None:
    """A free-text verdict is the one thing the eval cannot score. It is not written."""
    repo = tmp_path / "repo"
    repos.healthy(repo)
    labels = tmp_path / "labels.local.yaml"

    result = runner.invoke(
        app,
        [
            "label",
            "--corpus", str(_corpus(tmp_path / "corpus.yaml", repo)),
            "--labels", str(labels),
            "--limit", "1",
        ],
        input="pretty good\nquit\n",
    )

    assert result.exit_code == 0
    assert "not a verdict" in result.output
    assert not labels.exists()


def test_label_refuses_a_judged_verdict_where_nothing_was_looked_at(tmp_path: Path) -> None:
    """`planning_discipline` reads from L2 alone, and the corpus has no session logs.

    The harness forces the answer; this checks the loop enforces it rather than merely
    printing it. A `moderate` here would be ground truth invented out of nothing.
    """
    repo = tmp_path / "repo"
    repos.healthy(repo)
    labels = tmp_path / "labels.local.yaml"

    result = runner.invoke(
        app,
        [
            "label",
            "--corpus", str(_corpus(tmp_path / "corpus.yaml", repo)),
            "--labels", str(labels),
            "--limit", "4",
        ],
        # Three ordinary dimensions, then planning: a judged answer, then the forced one.
        input=(
            "insufficient_evidence\nnone\nthin on every count\n"
            "insufficient_evidence\nnone\nthin on every count\n"
            "insufficient_evidence\nnone\nthin on every count\n"
            "moderate\n"
            "not_collected\nno session log exists for this repository\n"
        ),
    )

    assert result.exit_code == 0, result.output
    assert "CANNOT BE JUDGED HERE" in result.output
    assert "expected one of not_collected" in result.output
    assert "4 label(s) written" in result.output


def test_label_catches_an_address_in_a_reason_before_it_is_written(tmp_path: Path) -> None:
    """The labeller retypes one line; the file is never left invalid mid-round."""
    repo = tmp_path / "repo"
    repos.healthy(repo)
    labels = tmp_path / "labels.local.yaml"

    result = runner.invoke(
        app,
        [
            "label",
            "--corpus", str(_corpus(tmp_path / "corpus.yaml", repo)),
            "--labels", str(labels),
            "--limit", "1",
        ],
        input="strong\nnone\nalice@example.com fixes her own defects\nquit\n",
    )

    assert result.exit_code == 0
    assert "not written" in result.output
    assert "email address" in result.output
    assert not labels.exists()


def test_label_skips_a_row_that_is_already_labelled(tmp_path: Path) -> None:
    from vouch.eval.labeling import assign_split
    from vouch.l4.dimensions import DIMENSIONS

    repo = tmp_path / "repo"
    repos.healthy(repo)
    corpus = _corpus(tmp_path / "corpus.yaml", repo)
    labels = tmp_path / "labels.local.yaml"

    def header(spec):
        return f"fixture  —  {spec.title}   [{assign_split('fixture', spec.key)}]"

    args = ["label", "--corpus", str(corpus), "--labels", str(labels), "--limit", "1"]
    first = runner.invoke(
        app, args, input="moderate\ntest_accompanies_fix\ntwelve commits, five with a test alongside\n"
    )
    assert header(DIMENSIONS[0]) in first.output, first.output

    # Second run: the first dimension is done, so the next pending one is offered instead.
    result = runner.invoke(
        app, args, input="insufficient_evidence\nnone\nnothing in the trail speaks to this\n"
    )

    assert result.exit_code == 0, result.output
    assert header(DIMENSIONS[0]) not in result.output
    assert header(DIMENSIONS[1]) in result.output


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


def test_profile_runs_end_to_end_to_a_share_link(tmp_path: Path, monkeypatch) -> None:
    """A repo goes all the way to a frozen, shareable snapshot — the 1e exit criterion.

    The judge is a bound mock, so this exercises the full assembly offline.
    """
    from vouch.ingest import ingest
    from vouch.l1.extract import extract_facts
    from vouch.l4.diffs import extract_diff
    from vouch.l4.grounding import build_allowlist
    from vouch.l4.mock import MockJudgeProvider, MockMode
    from vouch.l4.sampling import select_commits

    repo = tmp_path / "repo"
    repos.healthy(repo)

    snapshot = ingest(str(repo), cache_dir=tmp_path / "cache")
    facts = extract_facts(snapshot, SUBJECT, repo)
    provider = MockJudgeProvider(MockMode.HONEST)
    sample = select_commits(snapshot.commits, facts)
    provider.bind(build_allowlist(facts, [extract_diff(repo, c) for c in sample.commits]))
    monkeypatch.setattr("vouch.cli.build_default_provider", lambda: provider)

    web_dir = tmp_path / "profiles"
    result = runner.invoke(
        app,
        ["profile", str(repo), "--author", SUBJECT, "--web-dir", str(web_dir)],
    )

    assert result.exit_code == 0, result.output
    assert "share link: /p/" in result.output

    written = list(web_dir.glob("*.json"))
    assert len(written) == 1

    raw = written[0].read_text()
    profile = json.loads(raw)
    assert profile["subject"] == SUBJECT
    assert profile["profile_id"] == written[0].stem
    assert profile["limitations"]
    assert profile["risks_to_probe"]
    # The guarantee that survives all the way to the shared artefact.
    assert "score" not in profile
    # This run's repo is a tmp path, so the scan is live rather than notional.
    assert_no_machine_locals(raw, subject=SUBJECT)
