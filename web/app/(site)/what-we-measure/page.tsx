import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "What it measures · vouch",
  description:
    "Four dimensions, each backed by a fact with a denominator. Deliberately narrower than tools that claim to measure everything.",
};

const DIMENSIONS = [
  {
    title: "Verification discipline",
    question: "Does this engineer check their work in the commit trail and while writing it?",
    git: "Verifies whether fix commits carry associated test changes.",
    session: "Tracks whether tests or build runs closely followed code edits in the session.",
    note: "The primary dimension visible in both git history and session telemetry, demonstrating independent corroboration.",
    badge: "Git & Session",
  },
  {
    title: "Ownership",
    question: "Do they return to fix their own defects, with tests, over time?",
    git: "Tracks corrective returns to self-authored lines ≥14 days apart, follow-up latency, and revert recovery.",
    session: "Not collected (sessions cannot observe defects discovered months later).",
    note: "The two-week floor distinguishes sustained ownership from completing a single active feature branch.",
    badge: "Git-Only",
  },
  {
    title: "Scope control",
    question: "Do code changes stay inside what the commit message claims?",
    git: "Measures diff line spread across paths relative to stated subject intent.",
    session: "Tracks file edit oscillation frequency before branch completion.",
    note: "Focuses on commit focus and atomicity rather than total diff size.",
    badge: "Git & Session",
  },
  {
    title: "Planning discipline",
    question: "Do they plan before executing complex modifications?",
    git: "Not collected (commits record outcomes, not pre-execution planning).",
    session: "Tracks whether plan mode was invoked prior to execution steps.",
    note: "Rests exclusively on session telemetry. Reports 'not collected' when CLI telemetry is absent.",
    badge: "Session-Only",
  },
];

export default function WhatWeMeasurePage() {
  return (
    <main className="mx-auto max-w-4xl px-6 py-12 animate-fade-in">
      <header className="rounded-2xl border border-slate-200 bg-white p-8 shadow-xs mb-10">
        <p className="text-xs font-bold uppercase tracking-wider text-slate-500">
          Engineering Dimensions
        </p>
        <h1 className="mt-2 text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
          Four Dimensions, Strictly Grounded
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-relaxed text-slate-600">
          Vouch evaluates four specific habits, each backed by explicit denominators. If a dimension cannot be grounded in commit SHAs or session logs, it is not reported.
        </p>
      </header>

      {/* Dimensions List */}
      <div className="space-y-6">
        {DIMENSIONS.map((d) => (
          <article key={d.title} className="rounded-2xl border border-slate-200 bg-white p-6 tactile-card">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-lg font-bold text-slate-900">{d.title}</h2>
              <span className="rounded-md bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-700 border border-slate-200">
                {d.badge}
              </span>
            </div>
            <p className="mt-1 text-sm italic font-medium text-slate-500">"{d.question}"</p>

            <div className="mt-5 grid gap-3 sm:grid-cols-2">
              <div className="rounded-xl bg-slate-50/70 p-4 border border-slate-200/60">
                <span className="text-xs font-bold uppercase tracking-wider text-slate-500">From Git History</span>
                <p className="mt-1.5 text-xs text-slate-700 leading-relaxed">{d.git}</p>
              </div>
              <div className="rounded-xl bg-slate-50/70 p-4 border border-slate-200/60">
                <span className="text-xs font-bold uppercase tracking-wider text-slate-500">From Session Telemetry</span>
                <p className="mt-1.5 text-xs text-slate-700 leading-relaxed">{d.session}</p>
              </div>
            </div>

            <p className="mt-4 border-l-2 border-slate-300 pl-3.5 text-xs text-slate-600 leading-relaxed">
              {d.note}
            </p>
          </article>
        ))}
      </div>

      {/* Non-features */}
      <section className="mt-14 border-t border-slate-200/80 pt-10">
        <div className="mb-6">
          <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500">
            Design Non-Goals
          </h2>
          <p className="mt-1 text-xl font-bold text-slate-900">
            What Vouch deliberately omits
          </p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="rounded-xl border border-slate-200 bg-white p-5 tactile-card">
            <h3 className="text-sm font-bold text-slate-900">No Overall Score</h3>
            <p className="mt-2 text-xs text-slate-600 leading-relaxed">
              The document schema contains no field for an aggregate score. Viewers cannot reconstruct one.
            </p>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-5 tactile-card">
            <h3 className="text-sm font-bold text-slate-900">No Candidate Ranking</h3>
            <p className="mt-2 text-xs text-slate-600 leading-relaxed">
              There is no candidate database or percentile ranking across candidates.
            </p>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-5 tactile-card">
            <h3 className="text-sm font-bold text-slate-900">No Forced Verdicts</h3>
            <p className="mt-2 text-xs text-slate-600 leading-relaxed">
              <em>Insufficient evidence</em> is a standard verdict when commit counts fall below confidence floors.
            </p>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-5 tactile-card">
            <h3 className="text-sm font-bold text-slate-900">No Ungrounded Claims</h3>
            <p className="mt-2 text-xs text-slate-600 leading-relaxed">
              Single-contributor or squashed repos trigger confounds, suppressing invalid readings outright.
            </p>
          </div>
        </div>
      </section>
    </main>
  );
}
