"use client";

import { useState } from "react";
import Link from "next/link";

const QUESTIONS = [
  {
    id: "verification",
    q: "Are fixes shipped with tests?",
    tag: "VERIFICATION",
    verdict: "Strong",
    verdictStyle: "bg-emerald-50 text-emerald-800 border-emerald-200",
    summary: "Fix commits carry associated test updates in 87% of observed cases.",
    claims: [
      { text: "Added unit tests alongside fix for authentication edge-case", sha: "a1b2c3d4", path: "tests/test_auth.py" },
      { text: "Included integration test for session expiration handler", sha: "e5f6g7h8", path: "tests/test_session.py" },
    ],
  },
  {
    id: "ownership",
    q: "Do they return to fix own defects?",
    tag: "OWNERSHIP",
    verdict: "Moderate",
    verdictStyle: "bg-sky-50 text-sky-800 border-sky-200",
    summary: "Sustained return to self-authored lines observed with 18-day average follow-up latency.",
    claims: [
      { text: "Corrected memory leak in stream parser first touched 24 days prior", sha: "8f9a0b1c", path: "src/stream/parser.rs" },
    ],
  },
  {
    id: "scope",
    q: "Do changes stay focused?",
    tag: "SCOPE CONTROL",
    verdict: "Strong",
    verdictStyle: "bg-emerald-50 text-emerald-800 border-emerald-200",
    summary: "Diffs remain tightly scoped to stated commit subjects across 42 commits.",
    claims: [
      { text: "Commit diff isolated strictly to schema migration without refactoring noise", sha: "2d3e4f5a", path: "db/migrations/004.sql" },
    ],
  },
  {
    id: "planning",
    q: "Do they plan before execution?",
    tag: "PLANNING",
    verdict: "Not collected",
    verdictStyle: "bg-zinc-100 text-zinc-600 border-zinc-200",
    summary: "Rests on local session telemetry. Web-only analysis reports not collected.",
    claims: [],
  },
];

export default function ProfileIndexDemo() {
  const [activeId, setActiveId] = useState("verification");
  const activeItem = QUESTIONS.find((item) => item.id === activeId) || QUESTIONS[0];
  const [copiedSha, setCopiedSha] = useState<string | null>(null);

  const copySha = (sha: string) => {
    navigator.clipboard.writeText(sha);
    setCopiedSha(sha);
    setTimeout(() => setCopiedSha(null), 1800);
  };

  return (
    <div className="section-rail rounded-2xl p-1 overflow-hidden vouch-card">
      <div className="bg-zinc-900 px-4 py-2.5 flex items-center justify-between border-b border-zinc-800 text-xs font-mono">
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
          <span className="text-zinc-200 font-bold">VOUCH CAPABILITY DEMO</span>
          <span className="text-zinc-500">·</span>
          <span className="text-zinc-400">reecert/vouch</span>
        </div>
        <span className="text-zinc-500 hidden sm:inline">42 commits · 4 dimensions</span>
      </div>

      <div className="grid sm:grid-cols-[220px_1fr] bg-white divide-y sm:divide-y-0 sm:divide-x divide-zinc-200">
        {/* Left Question Selector Sidebar */}
        <div className="p-3 bg-zinc-50/50 space-y-1">
          <span className="block px-2 py-1 text-[10px] font-mono font-bold uppercase tracking-wider text-zinc-400">
            Ask the Profile
          </span>
          {QUESTIONS.map((item) => {
            const isActive = item.id === activeId;
            return (
              <button
                key={item.id}
                onClick={() => setActiveId(item.id)}
                className={`w-full text-left px-3 py-2.5 rounded-lg text-xs font-medium transition-all cursor-pointer flex items-center justify-between ${
                  isActive
                    ? "bg-zinc-900 text-white font-semibold shadow-xs"
                    : "text-zinc-700 hover:bg-zinc-200/60"
                }`}
              >
                <span>{item.q}</span>
                {isActive && <span className="font-mono text-[10px] text-zinc-400">→</span>}
              </button>
            );
          })}
        </div>

        {/* Right Active Finding Panel */}
        <div className="p-6">
          <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-zinc-100">
            <span className="text-[11px] font-mono font-bold uppercase tracking-wider text-zinc-500">
              {activeItem.tag}
            </span>
            <span className={`rounded-md border px-2.5 py-0.5 text-xs font-semibold ${activeItem.verdictStyle}`}>
              {activeItem.verdict}
            </span>
          </div>

          <p className="mt-4 text-sm text-zinc-800 leading-relaxed font-medium bg-zinc-50 p-3 rounded-lg border border-zinc-200/60">
            {activeItem.summary}
          </p>

          {activeItem.claims.length > 0 ? (
            <div className="mt-5">
              <span className="block text-[10px] font-mono font-bold uppercase tracking-wider text-zinc-400 mb-2">
                Ground-Truth Commit Citations
              </span>
              <div className="space-y-2">
                {activeItem.claims.map((claim, idx) => (
                  <div key={idx} className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 p-2.5 rounded-lg border border-zinc-200/80 bg-white text-xs">
                    <span className="text-zinc-700 font-medium">{claim.text}</span>
                    <button
                      onClick={() => copySha(claim.sha)}
                      className="inline-flex items-center gap-1.5 font-mono text-[11px] bg-zinc-100 px-2 py-1 rounded border border-zinc-200 text-zinc-800 hover:bg-zinc-200 transition-colors cursor-pointer shrink-0 self-start sm:self-auto"
                    >
                      <span>{claim.sha}</span>
                      <span className="text-zinc-400">· {claim.path}</span>
                      {copiedSha === claim.sha && <span className="text-emerald-600 font-bold ml-1">✓</span>}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <p className="mt-4 text-xs text-zinc-500 italic">
              Run the local CLI (<code className="font-mono text-zinc-700">vouch profile</code>) to correlate local session logs.
            </p>
          )}

          <div className="mt-6 pt-4 border-t border-zinc-100 flex items-center justify-between">
            <span className="text-[11px] font-mono text-zinc-400">Grounding Validator: Passed (100% SHA match)</span>
            <Link href="/connect" className="text-xs font-bold text-zinc-900 hover:underline">
              Generate for your repo →
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
