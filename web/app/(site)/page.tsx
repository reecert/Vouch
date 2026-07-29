import type { Metadata } from "next";
import Link from "next/link";
import { listProfileIds, loadProfile } from "@/lib/data";
import ProfileIndexDemo from "./ProfileIndexDemo";
import CopyCliBox from "./CopyCliBox";

export const metadata: Metadata = { alternates: { canonical: "/" } };
export const dynamic = "force-dynamic";

const PRODUCTS = [
  {
    n: "01",
    title: "Verification Discipline",
    desc: "Verifies whether fix commits carry associated test updates, in git commit trails and during active coding.",
    tag: "Git & Session",
  },
  {
    n: "02",
    title: "Sustained Ownership",
    desc: "Tracks corrective returns to self-authored lines over 14+ day intervals, follow-up latency, and revert recovery rates.",
    tag: "Git-Only",
  },
  {
    n: "03",
    title: "Scope Control",
    desc: "Evaluates commit atomicity and measures how far diff line changes spread beyond stated subject lines.",
    tag: "Git & Session",
  },
  {
    n: "04",
    title: "Planning Discipline",
    desc: "Monitors pre-execution plan mode entries in local Claude Code telemetry before complex edits begin.",
    tag: "Session-Only",
  },
];

const PROOF = [
  "Connect read-only.",
  "Keep your existing stack.",
  "First evidence in seconds.",
  "Every claim backed by SHA citations.",
];

export default function Home() {
  const samples =
    process.env.NODE_ENV === "production"
      ? []
      : listProfileIds()
          .map((id) => ({ id, profile: loadProfile(id) }))
          .filter((row) => row.profile !== null);

  return (
    <main className="mx-auto max-w-6xl px-6 py-12 animate-fade-in space-y-16">
      {/* Hero Section */}
      <section className="space-y-8 pt-4">
        <div className="space-y-4 max-w-4xl">
          <div className="inline-flex items-center gap-2 rounded-full border border-zinc-200 bg-white px-3.5 py-1 text-xs font-mono font-medium text-zinc-700 shadow-2xs">
            <span className="h-2 w-2 rounded-full bg-emerald-500" />
            <span>01 · GROUNDED ENGINEERING CAPABILITIES</span>
          </div>

          <h1 className="text-4xl font-extrabold tracking-tight text-zinc-900 sm:text-6xl leading-[1.1]">
            Your git history has <br className="hidden sm:inline" />
            <span className="text-zinc-600">evidence to disclose.</span>
          </h1>

          <p className="max-w-2xl text-base text-zinc-600 sm:text-lg leading-relaxed">
            Vouch connects read-only to your git repositories and local Claude Code sessions to find observable engineering habits, evidence gaps, and interview questions. Every claim is strictly grounded in commit SHAs.
          </p>
        </div>

        {/* CTA Actions */}
        <div className="flex flex-wrap items-center gap-4">
          <Link
            href="/connect"
            className="inline-flex items-center gap-2 rounded-xl bg-zinc-900 px-6 py-3.5 text-sm font-bold text-white shadow-xs hover:bg-zinc-800 transition-all active:scale-[0.98]"
          >
            <span>Connect a Repository</span>
            <span className="font-mono text-zinc-400">→</span>
          </Link>
          <Link
            href="/how-it-works"
            className="inline-flex items-center gap-2 rounded-xl border border-zinc-200 bg-white px-5 py-3.5 text-sm font-semibold text-zinc-700 hover:bg-zinc-50 transition-all"
          >
            <span>How it works</span>
          </Link>
        </div>

        {/* Proof checklist strip */}
        <ul className="flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-zinc-200/80 pt-6 text-xs font-medium text-zinc-600">
          {PROOF.map((item) => (
            <li key={item} className="flex items-center gap-2">
              <span className="flex h-4 w-4 items-center justify-center rounded-full bg-emerald-100 text-emerald-800 font-bold text-[10px]">
                ✓
              </span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </section>

      {/* Interactive Demo Section */}
      <section className="space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-2">
          <div>
            <span className="text-xs font-mono font-bold uppercase tracking-wider text-zinc-400">
              Interactive Preview
            </span>
            <h2 className="text-2xl font-bold text-zinc-900">Explore an Evidence Profile</h2>
          </div>
          <p className="text-xs text-zinc-500">
            Click questions to filter grounded citations and sample verdicts.
          </p>
        </div>

        <ProfileIndexDemo />
      </section>

      {/* 4-Card Numbered Product Grid */}
      <section className="space-y-6">
        <div>
          <span className="text-xs font-mono font-bold uppercase tracking-wider text-zinc-400">
            Measured Habits
          </span>
          <h2 className="text-2xl font-bold text-zinc-900">Four Evaluated Engineering Dimensions</h2>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {PRODUCTS.map((prod) => (
            <div
              key={prod.n}
              className="section-rail corner-node rounded-2xl p-6 vouch-card flex flex-col justify-between"
            >
              <div>
                <div className="flex items-center justify-between mb-4">
                  <span className="font-mono text-xl font-bold text-zinc-400">{prod.n}</span>
                  <span className="rounded bg-zinc-100 px-2 py-0.5 text-[10px] font-mono font-semibold text-zinc-600 border border-zinc-200">
                    {prod.tag}
                  </span>
                </div>
                <h3 className="text-base font-bold text-zinc-900">{prod.title}</h3>
                <p className="mt-2 text-xs text-zinc-600 leading-relaxed">{prod.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Generation Options (Web vs Local CLI) */}
      <section className="grid gap-6 sm:grid-cols-2">
        <div className="rounded-2xl border border-zinc-200 bg-white p-8 vouch-card">
          <div className="flex items-center gap-2 mb-3">
            <span className="flex h-6 w-6 items-center justify-center rounded-md bg-zinc-900 text-xs font-mono font-bold text-white">
              A
            </span>
            <h3 className="text-lg font-bold text-zinc-900">Connect via Web</h3>
          </div>
          <p className="text-sm text-zinc-600 leading-relaxed">
            Sign in with GitHub and select any public repo. Analyzes commit SHAs, diff atomicity, and verification habits directly on the server.
          </p>
          <Link
            href="/connect"
            className="mt-6 inline-flex items-center gap-1.5 text-sm font-bold text-zinc-900 hover:underline"
          >
            <span>Start Web Connection</span>
            <span className="font-mono">→</span>
          </Link>
        </div>

        <div className="rounded-2xl border border-zinc-200 bg-white p-8 vouch-card">
          <div className="flex items-center gap-2 mb-3">
            <span className="flex h-6 w-6 items-center justify-center rounded-md bg-zinc-900 text-xs font-mono font-bold text-white">
              B
            </span>
            <h3 className="text-lg font-bold text-zinc-900">Run Local CLI</h3>
          </div>
          <p className="text-sm text-zinc-600 leading-relaxed mb-4">
            Runs locally on your laptop to correlate Claude Code session logs with git commits. Keeps session logs private on your machine.
          </p>
          <CopyCliBox />
        </div>
      </section>

      {/* Sample Profiles (Development Mode) */}
      {samples.length > 0 && (
        <section className="rounded-2xl border border-zinc-200 bg-zinc-50/50 p-6 space-y-4">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono font-bold uppercase tracking-wider text-zinc-500">
              Local Snapshots (Dev Only)
            </span>
            <span className="rounded bg-amber-100 px-2 py-0.5 text-[10px] font-bold text-amber-800">
              Development
            </span>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            {samples.map(({ id, profile }) => (
              <Link
                key={id}
                href={`/p/${id}`}
                className="flex items-center justify-between rounded-xl border border-zinc-200 bg-white p-4 vouch-card"
              >
                <div>
                  <h4 className="text-sm font-bold text-zinc-900">{profile!.subject}</h4>
                  <p className="text-xs font-mono text-zinc-500 mt-0.5">{profile!.evidence_inspected.repo}</p>
                </div>
                <span className="text-xs font-mono font-bold text-zinc-400 group-hover:text-zinc-900">
                  Open →
                </span>
              </Link>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}
