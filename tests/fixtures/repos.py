"""Confound fixtures — synthetic repos that each trip exactly one detector.

Every history here is built from the same healthy baseline and then deformed along one
axis, so a test can attribute a change in L1's output to that axis alone.

Two properties make these usable as golden-file fixtures:

* **Stable SHAs.** A commit hash is fully determined by tree, message, author, committer
  and dates — none of which depend on the machine. Every date below carries an explicit
  ``+00:00`` offset, because a bare local timestamp would make git record the *builder's*
  timezone and the hashes would differ between a laptop and CI.
* **Cleared floors.** The baseline has enough subject commits and self-fixes to clear the
  minimum-n floors, so a suppressed fact in a variant is a real finding rather than an
  artefact of a small fixture.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from tests.fixtures.builder import Step, build_repo

ALICE = ("Alice Dev", "alice@example.com")  # the subject under evaluation
BOB = ("Bob Other", "bob@example.com")
DEPENDABOT = ("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com")
ALICE_ALT = ("Alice Dev", "alice@personal.dev")  # same display name, unclaimed address

_EPOCH = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)


def day(n: int) -> str:
    """Day ``n`` after the fixture epoch, with an explicit UTC offset."""
    return (_EPOCH + timedelta(days=n)).isoformat()


def src(marker: str) -> str:
    """A three-line source file. Changing ``marker`` modifies line 2 and only line 2.

    Single-line modification keeps `changed_old_lines` -> `blame_ranges` predictable, so a
    self-fix in a fixture blames to exactly the commit that wrote the line.
    """
    return f"def handler():\n    return {marker}\n    # tail\n"


def test_file(name: str) -> str:
    return f"def test_{name}():\n    assert handler() is not None\n"


def _baseline() -> list[Step]:
    """A healthy history: two authors, three self-fixes after a real gap, two with tests."""
    return [
        Step(ALICE, day(0), "feat: add auth handler", {"src/auth.py": src("None")}),
        Step(BOB, day(1), "feat: add billing", {"src/billing.py": src("1")}),
        Step(ALICE, day(2), "feat: add search", {"src/search.py": src("None")}),
        Step(ALICE, day(3), "feat: add cache", {"src/cache.py": src("None")}),
        Step(ALICE, day(5), "docs: describe the auth flow", {"README.md": "# Auth\n"}),
        Step(ALICE, day(8), "feat: add queue", {"src/queue.py": src("None")}),
        # --- three returns to own code, all past the 14-day gap ---
        Step(
            ALICE,
            day(20),
            "fix: handle expired token in auth",
            {"src/auth.py": src("0"), "tests/test_auth.py": test_file("auth")},
        ),
        Step(
            ALICE,
            day(25),
            "fix: correct search ranking",
            {"src/search.py": src("0"), "tests/test_search.py": test_file("search")},
        ),
        # ...this one ships no test, so ownership_loop is 2/3 rather than a suspicious 100%.
        Step(ALICE, day(30), "fix: cache eviction bug", {"src/cache.py": src("0")}),
        Step(BOB, day(31), "feat: add metrics", {"src/metrics.py": src("1")}),
        Step(ALICE, day(35), "refactor: tidy queue internals", {"src/queue.py": src("2")}),
        Step(ALICE, day(40), "feat: add ratelimit", {"src/ratelimit.py": src("None")}),
        Step(ALICE, day(45), "chore: bump deps", {"package-lock.json": '{"v": 2}\n'}),
        Step(ALICE, day(50), "feat: add webhooks", {"src/webhooks.py": src("None")}),
    ]


def healthy(path: Path) -> list[str]:
    """Two authors, clean history. Every fact measured, no confounds fire."""
    return build_repo(path, _baseline())


def solo(path: Path) -> list[str]:
    """One human author. `ownership_loop` becomes not_assessable, not merely weak."""
    steps = [s for s in _baseline() if s.author != BOB]
    return build_repo(path, steps)


def squash_merged(path: Path) -> list[str]:
    """GitHub squash-merge history: PR numbers appended to subject lines."""
    steps = _baseline()
    for i, s in enumerate(steps):
        if i % 2 == 0:  # half the history carries the marker, over the 30% threshold
            s.subject = f"{s.subject} (#{100 + i})"
    return build_repo(path, steps)


def bot_heavy(path: Path) -> list[str]:
    """One human plus a busy dependency bot — a repo that looks more collaborative than it is."""
    steps = _baseline()
    for i in range(6):
        steps.append(
            Step(
                DEPENDABOT,
                day(60 + i),
                f"chore(deps): bump lib-{i} from 1.0 to 1.1",
                {"package-lock.json": f'{{"v": {10 + i}}}\n'},
            )
        )
    return build_repo(path, steps)


def noisy(path: Path) -> list[str]:
    """Lockfile and vendored churn dominating the file touches."""
    steps = _baseline()
    for i in range(8):
        steps.append(
            Step(
                ALICE,
                day(60 + i),
                f"chore: vendor update {i}",
                {
                    "package-lock.json": f'{{"v": {20 + i}}}\n',
                    f"vendor/lib/mod_{i}.js": f"export const v = {i};\n",
                    f"dist/bundle_{i}.min.js": f"var v={i};\n",
                },
            )
        )
    return build_repo(path, steps)


def rebased(path: Path) -> list[str]:
    """Author dates preserved, committer dates rewritten — a replayed history."""
    steps = _baseline()
    for i, s in enumerate(steps):
        if i % 2 == 0:
            s.committer_date = day(90 + i)
    return build_repo(path, steps)


def aliased(path: Path) -> list[str]:
    """The subject also commits under a second, unclaimed address with the same name."""
    steps = _baseline()
    steps.append(
        Step(ALICE_ALT, day(60), "feat: add exporter", {"src/exporter.py": src("None")})
    )
    return build_repo(path, steps)


def short_window(path: Path) -> list[str]:
    """All of the subject's work inside a few days — no time for a return to be observable."""
    steps = []
    for i, s in enumerate(_baseline()):
        s.date = day(i // 3)  # compress ~50 days into ~5
        steps.append(s)
    return build_repo(path, steps)


def early_career(path: Path) -> list[str]:
    """The shape the product is actually for — and the one its floors were blind to.

    Modelled on `wagtail-contrib` in `eval/repos.yaml`: an early-career contributor to a
    large, healthy project. A few dozen commits, a handful of fix commits, **none** of them
    carrying a test. `MinN.fix_commits` is 3 and there are 5, so the floor is cleared and
    `test_accompanies_fix` publishes — the damning direction of exactly the failure the
    floors were built to stop in the flattering direction.

    Deliberately not deformed along any confound axis. Nothing here is wrong with the
    history; the reading of it was.
    """
    steps = [
        Step(BOB, day(0), "feat: initial import", {"src/core.py": src("None")}),
        Step(BOB, day(1), "feat: add the api", {"src/api.py": src("None")}),
        Step(BOB, day(2), "test: cover the core", {"tests/test_core.py": test_file("core")}),
    ]
    # Twelve ordinary contributions, none of them fixes.
    for i in range(12):
        steps.append(
            Step(
                ALICE,
                day(10 + i * 7),
                f"feat: add widget {i}",
                {f"src/widget_{i}.py": src("None")},
            )
        )
    # Five fix commits, none with a test. This is the 0/5 the report used to print as 0.0.
    for i in range(5):
        steps.append(
            Step(
                ALICE,
                day(120 + i * 20),
                f"fix: correct widget {i} boundary case",
                {f"src/widget_{i}.py": src("1")},
            )
        )
    return build_repo(path, steps)
