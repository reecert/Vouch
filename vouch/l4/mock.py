"""Mock judges — including the ones that lie, so the guard rails are tested against lies.

The v0 prototype tested its contracts with adversarial mocks (malformed JSON, hallucinated
SHAs, inflated scores), which is why those contracts were trustworthy. The same discipline
carries forward with one addition the new brief demands: an **over-eager** judge that
returns a strong verdict on evidence that was suppressed for being too thin. That is the
specific failure `insufficient_evidence` exists to prevent, so it needs an adversary.

These run in CI. No API key, no spend, no network.
"""
from __future__ import annotations

from enum import StrEnum
from typing import TypeVar

from pydantic import BaseModel

from vouch.l4.grounding import Allowlist
from vouch.l4.providers import ProviderError
from vouch.l4.schema import (
    Claim,
    CommitJudgment,
    Confidence,
    DimensionFinding,
    DimensionKey,
    FixNature,
    Locator,
    ScopeDiscipline,
    TestRelevance,
    Verdict,
)

__all__ = ["MockMode", "MockJudgeProvider"]

T = TypeVar("T", bound=BaseModel)


class MockMode(StrEnum):
    HONEST = "honest"
    HALLUCINATING = "hallucinating"  # cites commits it was never shown
    WRONG_PATH = "wrong_path"  # real SHA, but a file that commit never touched
    UNSOURCED = "unsourced"  # conclusive verdict, no claims at all
    OVEREAGER = "overeager"  # strong verdict on evidence too thin to support it
    FLAKY = "flaky"  # transport failures


class MockJudgeProvider:
    """A judge whose behaviour is chosen, not learned."""

    def __init__(
        self,
        mode: MockMode = MockMode.HONEST,
        allowlist: Allowlist | None = None,
    ) -> None:
        self.name = "mock"
        self.model = mode.value
        self.mode = mode
        self.allowlist = allowlist
        self.calls = 0

    def bind(self, allowlist: Allowlist) -> None:
        """Give the mock the same evidence the real judge would be shown."""
        self.allowlist = allowlist

    def is_available(self) -> bool:
        return True

    # -- helpers ---------------------------------------------------------------------

    def _real_locator(self) -> Locator:
        if self.allowlist and self.allowlist.pairs:
            sha, path = sorted(self.allowlist.pairs)[0]
            return Locator(sha=sha, path=path)
        if self.allowlist and self.allowlist.shas:
            return Locator(sha=sorted(self.allowlist.shas)[0])
        return Locator(sha="0" * 40)

    def _wrong_path_locator(self) -> Locator:
        real = self._real_locator()
        return Locator(sha=real.sha, path="src/never_touched_by_this_commit.py")

    def _claims(self) -> list[Claim]:
        match self.mode:
            case MockMode.HALLUCINATING:
                return [
                    Claim(
                        text="Fixed a race condition they introduced earlier.",
                        locators=[Locator(sha="deadbeefdeadbeefdeadbeefdeadbeef12345678")],
                    )
                ]
            case MockMode.WRONG_PATH:
                return [
                    Claim(
                        text="Repaired the auth path they wrote.",
                        locators=[self._wrong_path_locator()],
                    )
                ]
            case MockMode.UNSOURCED | MockMode.OVEREAGER:
                return []
            case _:
                return [
                    Claim(
                        text="Returned to repair their own code and shipped a test with it.",
                        locators=[self._real_locator()],
                    )
                ]

    # -- provider protocol -----------------------------------------------------------

    def complete(self, system: str, user: str, schema: type[T]) -> T:
        self.calls += 1
        if self.mode is MockMode.FLAKY:
            raise ProviderError("mock: simulated transport failure")

        if schema is CommitJudgment:
            return CommitJudgment(  # type: ignore[return-value]
                sha=self._real_locator().sha,
                fix_nature=(
                    FixNature.INSUFFICIENT_EVIDENCE
                    if self.mode is MockMode.HONEST and "truncated" in user
                    else FixNature.REAL_FIX
                ),
                test_relevance=TestRelevance.EXERCISES_FAILURE,
                scope=ScopeDiscipline.FOCUSED,
                note="Adjusted the expiry comparison and added a regression test.",
            )

        if schema is DimensionFinding:
            verdict = (
                Verdict.INSUFFICIENT_EVIDENCE
                if self.mode is MockMode.HONEST and "suppressed" in user
                else Verdict.STRONG
            )
            return DimensionFinding(  # type: ignore[return-value]
                dimension=DimensionKey.OWNERSHIP,  # overwritten by the orchestrator
                verdict=verdict,
                confidence=Confidence.HIGH,
                summary="Returns to their own defects and ships tests with the fix.",
                claims=self._claims(),
                limitations=["Based on one repository."],
                risks_to_probe=["Ask how they handle a defect found in someone else's code."],
            )

        raise ProviderError(f"mock: unsupported schema {schema.__name__}")
