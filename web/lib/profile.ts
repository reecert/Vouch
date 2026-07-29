/**
 * Types mirroring the Python `Profile` schema (vouch/l5/profile.py).
 *
 * Kept deliberately narrow: the viewer renders what the pipeline produced and computes
 * nothing of its own. In particular there is no aggregate score here either — if the
 * viewer could derive one, the guarantee that the profile has none would be cosmetic.
 */

export type Verdict =
  | "strong"
  | "moderate"
  | "limited"
  | "insufficient_evidence"
  | "not_collected"
  | "out_of_scope"
  | "contradicted";

export type Confidence = "high" | "moderate" | "low";

export type DimensionKey =
  | "verification_discipline"
  | "ownership"
  | "scope_control"
  | "planning_discipline";

export interface Locator {
  sha: string;
  path: string | null;
  hunk: [number, number] | null;
}

export interface Claim {
  text: string;
  locators: Locator[];
}

export interface DimensionFinding {
  dimension: DimensionKey;
  verdict: Verdict;
  confidence: Confidence;
  summary: string;
  claims: Claim[];
  limitations: string[];
  risks_to_probe: string[];
}

export interface EvidenceSummary {
  repo: string;
  head_sha: string;
  window_first: string | null;
  window_last: string | null;
  n_commits_by_subject: number;
  n_commits_in_repo: number;
  n_diffs_read: number;
  n_diffs_available: number;
  n_sessions: number;
  session_telemetry: boolean;
  excluded_paths: Record<string, number>;
  measured_facts: number;
  withheld_facts: number;
}

export interface CorroborationSummary {
  ran: boolean;
  n_commits: number;
  n_corroborated: number;
  n_ambiguous: number;
  n_uncorroborated: number;
}

export interface Confound {
  key: string;
  severity: "info" | "warn" | "invalidating";
  direction: "overstates" | "understates" | "unknown";
  detail: string;
  affects: string[];
}

export interface Provenance {
  l1_schema: string;
  /** Absent on profiles built before the session snapshot was recorded. */
  session_snapshot?: string;
  judge_model: string;
  prompt_version: string;
  downgrades: string[];
  generated_at: string | null;
}

export interface Profile {
  schema_version: string;
  profile_id: string;
  subject: string;
  evidence_inspected: EvidenceSummary;
  findings: DimensionFinding[];
  risks_to_probe: string[];
  corroboration: CorroborationSummary;
  confounds: Confound[];
  limitations: string[];
  provenance: Provenance;
}

export const DIMENSION_TITLES: Record<DimensionKey, string> = {
  verification_discipline: "Verification discipline",
  ownership: "Ownership",
  scope_control: "Scope control",
  planning_discipline: "Planning discipline",
};

export const DIMENSION_QUESTIONS: Record<DimensionKey, string> = {
  verification_discipline:
    "Do they check their work, in the commit trail and while writing it?",
  ownership: "Do they return to fix their own defects, with tests, over time?",
  scope_control: "Do changes stay inside what they claim to be?",
  planning_discipline: "Do they plan before executing?",
};

/** Human-facing label. `insufficient_evidence` is stated plainly, never softened. */
export const VERDICT_LABELS: Record<Verdict, string> = {
  strong: "Strong",
  moderate: "Moderate",
  limited: "Limited",
  insufficient_evidence: "Insufficient evidence",
  not_collected: "Not collected",
  out_of_scope: "Out of scope",
  contradicted: "Contradicted",
};

/** Declining verdicts are neutral, never alarm colours: they are not a mark against anyone. */
export const VERDICT_STYLES: Record<Verdict, string> = {
  strong: "bg-emerald-50/80 text-emerald-800 border border-emerald-200/80",
  moderate: "bg-sky-50/80 text-sky-800 border border-sky-200/80",
  limited: "bg-amber-50/80 text-amber-800 border border-amber-200/80",
  insufficient_evidence: "bg-slate-100/80 text-slate-700 border border-slate-200",
  not_collected: "bg-slate-100/80 text-slate-600 border border-slate-200",
  out_of_scope: "bg-slate-100/80 text-slate-600 border border-slate-200",
  contradicted: "bg-rose-50/80 text-rose-800 border border-rose-200/80",
};

export const CONFIDENCE_LABELS: Record<Confidence, string> = {
  high: "High confidence",
  moderate: "Moderate confidence",
  low: "Low confidence",
};

export function shortSha(sha: string): string {
  return sha.slice(0, 8);
}
