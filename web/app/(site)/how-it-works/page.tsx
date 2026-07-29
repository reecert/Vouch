import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "How it works · vouch",
  description:
    "Five layers: git facts, session metrics, the join between them, diff-level judgment, and the assembled document.",
};

const LAYERS = [
  {
    n: "L1",
    name: "Extraction",
    title: "Git history becomes deterministic facts",
    body: "Arithmetic only, no model. Commits are parsed, bots and lockfile churn are filtered out, and multi-alias email identities are unified. Produces byte-identical fact payloads.",
    badge: "Deterministic",
  },
  {
    n: "L2",
    name: "Session Telemetry",
    title: "Local sessions become strict metric counts",
    body: "CLI execution only. Local Claude Code session logs are parsed into an allow-listed schema on your device. Raw prompt texts and free-text logs never leave your computer.",
    badge: "Local-Only",
  },
  {
    n: "L3",
    name: "Corroboration",
    title: "Sessions are joined to git commits",
    body: "Correlates commit timestamps against local sessions. Commits are tagged as corroborated, ambiguous, or uncorroborated—never scored.",
    badge: "Joint Evidence",
  },
  {
    n: "L4",
    name: "Grounded Judge",
    title: "Diffs are evaluated with mandatory SHA citations",
    body: "Model evaluates diff samples with strict rules: every claim MUST cite a commit SHA and path. Claims lacking citations are automatically rejected.",
    badge: "Anti-Hallucination",
  },
  {
    n: "L5",
    name: "Document Assembly",
    title: "Final capability profile is assembled",
    body: "Evidence metadata presented first, followed by dimension readings, screener interview questions, and automatic limitations derived from detected confounds.",
    badge: "Immutable Document",
  },
];

const RULES = [
  {
    title: "Denominators stay visible",
    body: "A single fix with a test displays as 1/1, never 100%. If sample sizes are too small, values are withheld rather than rounded.",
  },
  {
    title: "Confounds suppress invalid metrics",
    body: "Single-author repos flag an ownership confound, changing readings to 'not assessable' rather than generating misleading conclusions.",
  },
  {
    title: "Evidence checks only ever downgrade",
    body: "Grounding checks verify model statements against L1 git facts. If discrepancy exists, the verdict is strictly downgraded.",
  },
  {
    title: "Frozen share links",
    body: "Document IDs are content hashes. Revoking permanently deletes the document from resolution.",
  },
];

export default function HowItWorksPage() {
  return (
    <main className="mx-auto max-w-4xl px-6 py-12 animate-fade-in">
      <header className="rounded-2xl border border-slate-200 bg-white p-8 shadow-xs mb-10">
        <p className="text-xs font-bold uppercase tracking-wider text-slate-500">
          Architecture
        </p>
        <h1 className="mt-2 text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
          Five Layers, Uncompromising Rules
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-relaxed text-slate-600">
          Vouch enforces a strict pipeline order: every claim produced at the end must pass ground-truth validation against facts extracted at the beginning.
        </p>
      </header>

      {/* Pipeline Diagram */}
      <section className="space-y-4">
        <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-4">
          Analysis Pipeline
        </h2>
        {LAYERS.map((l, index) => (
          <div key={l.n} className="relative">
            <div className="rounded-2xl border border-slate-200 bg-white p-6 tactile-card flex flex-col sm:flex-row sm:items-start gap-4">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-slate-900 font-mono text-sm font-bold text-white shadow-2xs">
                {l.n}
              </div>
              <div className="flex-1">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-base font-semibold text-slate-900">{l.title}</h3>
                  <span className="rounded-md bg-slate-100 px-2.5 py-0.5 text-xs font-semibold text-slate-700 border border-slate-200">
                    {l.badge}
                  </span>
                </div>
                <p className="mt-2 text-sm leading-relaxed text-slate-600">{l.body}</p>
              </div>
            </div>

            {index < LAYERS.length - 1 && (
              <div className="flex justify-center my-1">
                <div className="h-4 w-0.5 bg-slate-300" />
              </div>
            )}
          </div>
        ))}
      </section>

      {/* Rules Section */}
      <section className="mt-14 border-t border-slate-200/80 pt-10">
        <div className="mb-6">
          <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500">
            Guarantees
          </h2>
          <p className="mt-1 text-xl font-bold text-slate-900">
            Rules that never bend
          </p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          {RULES.map((r) => (
            <div key={r.title} className="rounded-xl border border-slate-200 bg-white p-5 tactile-card">
              <h3 className="text-sm font-bold text-slate-900">{r.title}</h3>
              <p className="mt-2 text-xs leading-relaxed text-slate-600">{r.body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Comparison section */}
      <section className="mt-14 rounded-2xl border border-slate-200 bg-white p-8 tactile-card">
        <h2 className="text-base font-bold text-slate-900">
          Browser Connection vs. Local CLI
        </h2>
        <p className="mt-2 text-sm text-slate-600 leading-relaxed max-w-2xl">
          Browser connections execute L1, L4, and L5 (git commit analysis). Local session telemetry (L2 & L3) requires the CLI because session logs live on your laptop and never get uploaded to external servers.
        </p>

        <div className="mt-6 flex flex-wrap items-center gap-4">
          <Link
            href="/connect"
            className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2.5 text-xs font-semibold text-white shadow-xs hover:bg-slate-800 transition-colors"
          >
            Connect Repository
          </Link>
          <Link
            href="/"
            className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 transition-colors"
          >
            Get CLI Command
          </Link>
        </div>
      </section>
    </main>
  );
}
