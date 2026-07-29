"use client";

import { useState } from "react";
import type {
  Claim as ClaimType,
  Confound,
  DimensionFinding,
  DimensionKey,
  Profile,
} from "@/lib/profile";
import {
  CONFIDENCE_LABELS,
  DIMENSION_QUESTIONS,
  DIMENSION_TITLES,
  VERDICT_LABELS,
  VERDICT_STYLES,
  shortSha,
} from "@/lib/profile";

function Section({
  number,
  title,
  subtitle,
  children,
}: {
  number?: string;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-4 pt-10 border-t border-zinc-200/80">
      <div>
        {number && (
          <span className="text-[11px] font-mono font-bold uppercase tracking-wider text-zinc-400">
            {number} · {title}
          </span>
        )}
        {!number && (
          <h2 className="text-xs font-bold uppercase tracking-wider text-zinc-500">
            {title}
          </h2>
        )}
        {subtitle ? (
          <p className="mt-1 text-sm text-zinc-600">{subtitle}</p>
        ) : null}
      </div>
      {children}
    </section>
  );
}

function Stat({
  label,
  value,
  highlight = false,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div className="flex flex-col justify-between rounded-xl border border-zinc-200/80 bg-zinc-50/50 p-3.5">
      <dt className="text-[11px] font-mono font-medium text-zinc-500">{label}</dt>
      <dd
        className={`mt-1 text-sm font-semibold tabular-nums ${
          highlight ? "text-zinc-900 font-mono" : "text-zinc-800"
        }`}
      >
        {value}
      </dd>
    </div>
  );
}

function Claim({ claim }: { claim: ClaimType }) {
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);

  const copyLocator = (locText: string, index: number) => {
    navigator.clipboard.writeText(locText);
    setCopiedIndex(index);
    setTimeout(() => setCopiedIndex(null), 1800);
  };

  return (
    <li className="text-sm leading-relaxed text-zinc-800 bg-zinc-50/70 p-3.5 rounded-xl border border-zinc-200/60">
      <span>{claim.text}</span>{" "}
      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
        {claim.locators.map((loc, i) => {
          const text = loc.path ? `${shortSha(loc.sha)}:${loc.path}` : shortSha(loc.sha);
          return (
            <button
              key={`${loc.sha}-${loc.path ?? ""}-${i}`}
              onClick={() => copyLocator(text, i)}
              title="Click to copy SHA reference"
              className="inline-flex items-center gap-1.5 rounded-md border border-zinc-200 bg-white px-2.5 py-1 font-mono text-xs font-medium text-zinc-800 hover:border-zinc-300 hover:bg-zinc-100 transition-colors shadow-2xs cursor-pointer"
            >
              <span>{shortSha(loc.sha)}</span>
              {loc.path ? <span className="text-zinc-400">· {loc.path}</span> : null}
              {copiedIndex === i ? (
                <span className="ml-1 text-[10px] text-emerald-600 font-bold">✓ Copied</span>
              ) : null}
            </button>
          );
        })}
      </div>
    </li>
  );
}

function Finding({ finding }: { finding: DimensionFinding }) {
  const key = finding.dimension as DimensionKey;
  return (
    <article className="section-rail corner-node rounded-2xl p-6 vouch-card">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-zinc-400">
            DIMENSION
          </span>
          <h3 className="text-lg font-bold text-zinc-900 mt-0.5">
            {DIMENSION_TITLES[key] ?? key}
          </h3>
          <p className="mt-1 text-xs text-zinc-500 italic">
            "{DIMENSION_QUESTIONS[key]}"
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`rounded-md px-3 py-1 text-xs font-semibold shadow-2xs ${
              VERDICT_STYLES[finding.verdict]
            }`}
          >
            {VERDICT_LABELS[finding.verdict]}
          </span>
          <span className="rounded-md bg-zinc-100 px-2.5 py-1 text-xs font-mono text-zinc-600 border border-zinc-200">
            {CONFIDENCE_LABELS[finding.confidence]}
          </span>
        </div>
      </div>

      <p className="mt-4 text-sm leading-relaxed text-zinc-800 bg-zinc-50 p-4 rounded-xl border border-zinc-200/60 font-medium">
        {finding.summary}
      </p>

      {finding.claims.length > 0 ? (
        <div className="mt-5">
          <h4 className="text-[11px] font-mono font-bold uppercase tracking-wider text-zinc-400 mb-2">
            Grounded Claims ({finding.claims.length})
          </h4>
          <ul className="space-y-2.5">
            {finding.claims.map((claim, i) => (
              <Claim key={i} claim={claim} />
            ))}
          </ul>
        </div>
      ) : null}

      {finding.limitations.length > 0 ? (
        <div className="mt-5 border-t border-zinc-100 pt-3">
          <h4 className="text-[10px] font-mono font-bold uppercase tracking-wider text-zinc-400 mb-1.5">
            Stated Limitations
          </h4>
          <ul className="space-y-1 text-xs text-zinc-500">
            {finding.limitations.map((lim, i) => (
              <li key={i} className="flex items-start gap-1.5">
                <span className="text-zinc-400">—</span>
                <span>{lim}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </article>
  );
}

function RiskItem({ risk, index }: { risk: string; index: number }) {
  const [copied, setCopied] = useState(false);

  const copyQuestion = () => {
    navigator.clipboard.writeText(risk);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  return (
    <li className="flex flex-col sm:flex-row sm:items-start justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50/50 p-4 transition-all hover:bg-amber-50/80">
      <div className="flex gap-3 text-sm leading-relaxed text-zinc-800">
        <span className="mt-0.5 shrink-0 font-mono text-xs font-bold text-amber-800 bg-amber-100 px-2 py-0.5 rounded">
          Q{String(index + 1).padStart(2, "0")}
        </span>
        <span className="font-semibold">{risk}</span>
      </div>
      <button
        onClick={copyQuestion}
        className="shrink-0 self-end sm:self-auto rounded-md border border-amber-300 bg-white px-3 py-1 text-xs font-semibold text-amber-900 hover:bg-amber-100 transition-colors cursor-pointer shadow-2xs"
      >
        {copied ? "✓ Copied" : "Copy Question"}
      </button>
    </li>
  );
}

export default function ProfileView({ profile }: { profile: Profile }) {
  const ev = profile.evidence_inspected;
  const corr = profile.corroboration;
  const [shareCopied, setShareCopied] = useState(false);

  const copyShareLink = () => {
    navigator.clipboard.writeText(window.location.href);
    setShareCopied(true);
    setTimeout(() => setShareCopied(false), 2000);
  };

  return (
    <main className="mx-auto max-w-5xl px-6 py-12 animate-fade-in space-y-12">
      {/* Document Header Rail */}
      <header className="section-rail corner-node rounded-2xl p-8 vouch-card space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <span className="rounded-full bg-zinc-900 px-3 py-1 text-[11px] font-mono font-bold text-white">
              VERIFIED PROFILE
            </span>
            <span className="text-xs font-mono text-zinc-500">
              ID: {profile.profile_id}
            </span>
          </div>

          <button
            onClick={copyShareLink}
            className="inline-flex items-center gap-2 rounded-lg border border-zinc-200 bg-white px-3.5 py-1.5 text-xs font-semibold text-zinc-800 hover:bg-zinc-50 transition-colors shadow-2xs cursor-pointer"
          >
            <svg className="h-3.5 w-3.5 text-zinc-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
            </svg>
            <span>{shareCopied ? "Link Copied!" : "Copy Share Link"}</span>
          </button>
        </div>

        <div>
          <h1 className="text-3xl font-extrabold tracking-tight text-zinc-900 sm:text-4xl">
            {profile.subject}
          </h1>
          <p className="mt-2 text-sm leading-relaxed text-zinc-600 max-w-2xl">
            Engineering capability profile generated from public git history
            {ev.session_telemetry ? " and local Claude Code session telemetry" : ""}.
            Cites exact commit SHAs and explicitly states evidence boundaries.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2 pt-4 border-t border-zinc-100 text-xs font-mono">
          <span className="rounded bg-zinc-100 px-2.5 py-1 text-zinc-800 font-bold border border-zinc-200">
            repo: {ev.repo}
          </span>
          <span className="rounded bg-zinc-100 px-2.5 py-1 text-zinc-700 border border-zinc-200">
            head: {shortSha(ev.head_sha)}
          </span>
          {ev.window_first && ev.window_last ? (
            <span className="rounded bg-zinc-100 px-2.5 py-1 text-zinc-700 border border-zinc-200">
              window: {ev.window_first} → {ev.window_last}
            </span>
          ) : null}
        </div>
      </header>

      {/* 01 · EVIDENCE INSPECTED */}
      <Section
        number="01"
        title="EVIDENCE INSPECTED"
        subtitle="Stated provenance prior to forming findings."
      >
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="REPOSITORY" value={ev.repo} highlight />
          <Stat
            label="COMMITS INSPECTED"
            value={`${ev.n_commits_by_subject} / ${ev.n_commits_in_repo}`}
            highlight
          />
          <Stat
            label="DIFFS ANALYZED"
            value={
              ev.n_diffs_available
                ? `${ev.n_diffs_read} / ${ev.n_diffs_available}`
                : "None"
            }
          />
          <Stat
            label="FACTS MEASURED"
            value={`${ev.measured_facts} / ${ev.measured_facts + ev.withheld_facts}`}
          />
          <Stat
            label="LOCAL SESSIONS"
            value={ev.session_telemetry ? String(ev.n_sessions) : "Not collected"}
          />
          <Stat label="HEAD SHA" value={shortSha(ev.head_sha)} />
          <Stat
            label="ACTIVE WINDOW"
            value={
              ev.window_first && ev.window_last
                ? `${ev.window_first} to ${ev.window_last}`
                : "—"
            }
          />
          <Stat
            label="EXCLUDED NOISE"
            value={
              Object.keys(ev.excluded_paths).length
                ? Object.entries(ev.excluded_paths)
                    .map(([k, v]) => `${v} ${k}`)
                    .join(", ")
                : "None"
            }
          />
        </dl>
      </Section>

      {/* 02 · INTERVIEW QUESTIONS */}
      {profile.risks_to_probe.length > 0 && (
        <Section
          number="02"
          title="INTERVIEW QUESTIONS FOR SCREENER"
          subtitle="Derived directly from evidence gaps and commit pattern ambiguities."
        >
          <div className="rounded-2xl border border-amber-200 bg-amber-50/40 p-6">
            <ol className="space-y-3">
              {profile.risks_to_probe.map((risk, i) => (
                <RiskItem key={i} risk={risk} index={i} />
              ))}
            </ol>
          </div>
        </Section>
      )}

      {/* 03 · MEASURED DIMENSIONS */}
      <Section
        number="03"
        title="MEASURED DIMENSIONS"
        subtitle="Reported independently without aggregate scoring."
      >
        <div className="space-y-6">
          {profile.findings.map((finding) => (
            <Finding key={finding.dimension} finding={finding} />
          ))}
        </div>
      </Section>

      {/* 04 · SESSION CORROBORATION */}
      <Section
        number="04"
        title="SESSION CORROBORATION"
        subtitle="Cross-referencing git commits with local Claude Code session telemetry."
      >
        <div className="section-rail corner-node rounded-2xl p-6 vouch-card">
          {corr.ran ? (
            <p className="text-sm leading-relaxed text-zinc-800 font-medium">
              <span className="font-bold text-zinc-900 font-mono">
                {corr.n_corroborated} of {corr.n_commits} commits
              </span>{" "}
              have corresponding local session evidence behind them
              {corr.n_ambiguous > 0 ? `, with ${corr.n_ambiguous} ambiguous matching sessions` : ""}.
            </p>
          ) : (
            <p className="text-sm leading-relaxed text-zinc-600">
              Commits were analyzed via web git history alone (session telemetry not collected). Run local CLI to include session logs.
            </p>
          )}
        </div>
      </Section>

      {/* 05 · CONFOUND AUDIT */}
      {profile.confounds.length > 0 && (
        <Section
          number="05"
          title="CONFOUND DETECTION AUDIT"
          subtitle="Structural repository confounds detected prior to evaluation."
        >
          <div className="grid gap-4 sm:grid-cols-2">
            {profile.confounds.map((c) => (
              <div key={c.key} className="rounded-xl border border-zinc-200 bg-white p-5 vouch-card">
                <div className="flex items-center justify-between gap-2">
                  <span className="rounded px-2 py-0.5 font-mono text-[10px] font-bold uppercase bg-zinc-100 text-zinc-800 border border-zinc-200">
                    {c.severity}
                  </span>
                  <span className="font-mono text-xs text-zinc-500">{c.direction}</span>
                </div>
                <h4 className="mt-2 text-sm font-bold text-zinc-900 capitalize">
                  {c.key.replace(/_/g, " ")}
                </h4>
                <p className="mt-1 text-xs text-zinc-600 leading-relaxed">{c.detail}</p>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* Provenance Footer */}
      <footer className="rounded-xl border border-zinc-200 bg-zinc-100/60 p-6 text-xs text-zinc-500 font-mono flex flex-wrap items-center justify-between gap-2">
        <span>Snapshot Hash: {profile.profile_id}</span>
        <span>
          {profile.provenance.judge_model ? `Judge: ${profile.provenance.judge_model}` : ""}
          {profile.provenance.prompt_version ? ` · Prompt: ${profile.provenance.prompt_version}` : ""}
        </span>
      </footer>
    </main>
  );
}
