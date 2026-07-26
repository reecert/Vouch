"""Path classification — including the over-match the v0 regex shipped with."""
from __future__ import annotations

import pytest

from vouch.l1.paths import PathKind, classify, is_noise, is_significant, is_test


@pytest.mark.parametrize(
    "path,kind",
    [
        # source
        ("src/auth.py", PathKind.SOURCE),
        ("app/models/user.rb", PathKind.SOURCE),
        ("main.go", PathKind.SOURCE),
        # tests, by directory and by filename convention
        ("tests/test_auth.py", PathKind.TEST),
        ("test/helpers.rb", PathKind.TEST),
        ("src/__tests__/button.js", PathKind.TEST),
        ("conftest.py", PathKind.TEST),
        ("pkg/server_test.go", PathKind.TEST),
        ("src/Button.test.tsx", PathKind.TEST),
        ("src/api.spec.ts", PathKind.TEST),
        ("src/UserServiceTest.java", PathKind.TEST),
        # lockfiles
        ("package-lock.json", PathKind.LOCKFILE),
        ("api/poetry.lock", PathKind.LOCKFILE),
        ("go.sum", PathKind.LOCKFILE),
        # vendored
        ("vendor/github.com/pkg/errors/errors.go", PathKind.VENDORED),
        ("node_modules/left-pad/index.js", PathKind.VENDORED),
        ("third_party/zlib/zlib.c", PathKind.VENDORED),
        # generated
        ("dist/bundle.min.js", PathKind.GENERATED),
        ("build/output.o", PathKind.GENERATED),
        ("api/schema_pb2.py", PathKind.GENERATED),
        ("src/api.pb.go", PathKind.GENERATED),
        ("app/__snapshots__/view.snap", PathKind.GENERATED),
        # docs
        ("README.md", PathKind.DOCS),
        ("docs/plan.md", PathKind.DOCS),
    ],
)
def test_classify(path: str, kind: PathKind) -> None:
    assert classify(path) is kind


@pytest.mark.parametrize(
    "path",
    [
        "testing/server.py",  # v0's `(^|/)(tests?|...)` matched the "test" inside "testing"
        "src/latest/config.py",
        "src/contest_runner.py",
        "protest/views.py",
    ],
)
def test_test_lookalikes_are_source(path: str) -> None:
    """Segment matching, not substring matching. `testing/` is not a test directory."""
    assert classify(path) is PathKind.SOURCE
    assert not is_test(path)


def test_vendored_wins_over_test() -> None:
    """A test file inside a vendored dependency is not this engineer's test."""
    assert classify("node_modules/foo/test/index.test.js") is PathKind.VENDORED
    assert not is_test("node_modules/foo/test/index.test.js")


def test_significance_and_noise_partition() -> None:
    assert is_significant("src/auth.py")
    assert is_significant("tests/test_auth.py")
    assert not is_significant("package-lock.json")

    assert is_noise("package-lock.json")
    assert is_noise("vendor/lib.go")
    assert is_noise("dist/app.min.js")
    # Docs are excluded from fact denominators but are not machine-authored noise.
    assert not is_noise("README.md")
    assert not is_significant("README.md")
