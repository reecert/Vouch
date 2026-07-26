"""The judge prompt, versioned by ``config.prompt_version``.

The model reasons ONLY over the rendered signals + commit index below. It never sees a
diff or the repo. It must cite SHAs drawn from the provided commit index; the grounding
validator rejects anything else.
"""
from __future__ import annotations

import json

from vouch.config import Config
from vouch.schemas import EvidenceBundle

_SYSTEM = """\
You are a careful engineering-capability assessor. You evaluate ONE dimension: ownership —
does this engineer return to fix their own bugs, with tests, over time?

You are given ONLY pre-computed, deterministic signals and a commit index. You have NOT
seen the diffs or the repository. Do not speculate beyond the signals. Do not invent
commits. Every SHA you cite MUST appear in the commit index provided.

Weigh the signals roughly by the given weights, but you are the final arbiter: a high
score requires genuinely supportive evidence, not just non-zero values. Calibrate
`confidence` to how much evidence there is — few commits or thin signals => low confidence.

Return ONLY a JSON object with EXACTLY these fields:
  "dimension":       string, always "ownership"
  "score":           number 0..1  (ownership strength)
  "confidence":      number 0..1  (how sure you are, given evidence volume/quality)
  "freshness":       string "YYYY-MM-DD" (date of the most recent supporting commit)
  "rationale":       string; MUST reference the specific SHAs you relied on
  "cited_evidence":  array of SHA strings, each taken verbatim from the commit index
No prose outside the JSON.
"""


def _render_signals(bundle: EvidenceBundle, config: Config) -> str:
    lines = []
    for s in bundle.signals:
        weight = config.signal_weights.get(s.key, 0.0)
        lines.append(
            f"- {s.key} (weight {weight}): value={s.value}; "
            f"backed by {len(s.evidence)} commit(s): {s.evidence}"
        )
    return "\n".join(lines)


def _render_index(bundle: EvidenceBundle) -> str:
    rows = []
    for sha, m in bundle.commit_index.items():
        rows.append(
            f'  "{sha}": {json.dumps({"date": m.authored_at.date().isoformat(), "subject": m.subject, "files": m.n_files, "touched_tests": m.touched_tests})}'
        )
    return "{\n" + ",\n".join(rows) + "\n}"


def render_prompt(bundle: EvidenceBundle, config: Config) -> str:
    """Render the judge prompt for ``bundle`` under ``config.prompt_version``."""
    return f"""{_SYSTEM}

[prompt_version: {config.prompt_version}]

REPO: {bundle.repo}
SUBJECT (author under evaluation): {bundle.subject}
DIMENSION: {bundle.dimension}
ACTIVITY WINDOW: {bundle.window_first} .. {bundle.window_last} \
({bundle.n_commits_by_subject} commits by subject)

SIGNALS:
{_render_signals(bundle, config)}

COMMIT INDEX (the ONLY SHAs you may cite):
{_render_index(bundle)}

Produce the JSON verdict now."""
