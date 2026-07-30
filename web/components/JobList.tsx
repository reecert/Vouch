"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import { useCopied } from "@/lib/useCopied";

type Job = {
  id: string;
  full_name: string;
  author_email: string;
  status: "queued" | "running" | "done" | "failed" | "revoked";
  reason: string;
  profile_id: string;
  created_at: string;
  finished_at: string;
};

const STATUS_LABEL: Record<Job["status"], string> = {
  queued: "Queued",
  running: "Building…",
  done: "Ready",
  failed: "Did not finish",
  revoked: "Revoked",
};

const STATUS_STYLE: Record<Job["status"], string> = {
  queued: "bg-slate-100 text-slate-700 border-slate-200",
  running: "bg-sky-50 text-sky-800 border-sky-200 animate-pulse",
  done: "bg-emerald-50 text-emerald-800 border-emerald-200",
  failed: "bg-slate-100 text-slate-700 border-slate-200",
  revoked: "bg-slate-100 text-slate-400 border-slate-200",
};

export default function JobList() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [busy, setBusy] = useState("");
  const [copiedId, copy] = useCopied<string>();

  const load = useCallback(async () => {
    const res = await fetch("/api/jobs", { cache: "no-store" });
    if (res.ok) setJobs(((await res.json()) as { jobs: Job[] }).jobs);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const pending = jobs?.some((j) => j.status === "queued" || j.status === "running") ?? false;
  useEffect(() => {
    if (!pending) return;
    const timer = setInterval(() => void load(), 4000);
    return () => clearInterval(timer);
  }, [pending, load]);

  async function revoke(job: Job) {
    if (!confirm(`Revoke this profile? The link will stop resolving and the document will be permanently deleted.`))
      return;
    setBusy(job.id);
    await fetch(`/api/jobs/${job.id}`, { method: "DELETE" });
    setBusy("");
    void load();
  }

  const copyLink = (profileId: string) =>
    copy(`${window.location.origin}/p/${profileId}`, profileId);

  if (jobs === null) {
    return (
      <div className="mt-6 flex items-center gap-3 rounded-xl border border-slate-200 bg-white p-6 tactile-card">
        <div className="h-4 w-4 animate-spin rounded-full border-2 border-slate-900 border-t-transparent" />
        <span className="text-sm font-medium text-slate-600">Loading profile documents…</span>
      </div>
    );
  }

  if (jobs.length === 0) {
    return (
      <div className="mt-6 rounded-2xl border border-dashed border-slate-300 bg-slate-50/50 p-8 text-center">
        <h3 className="text-base font-semibold text-slate-900">No profiles generated yet</h3>
        <p className="mt-1 max-w-sm mx-auto text-sm text-slate-600">
          Connect a repository to build your first evidence-grounded capability profile.
        </p>
        <Link
          href="/connect"
          className="mt-5 inline-flex items-center rounded-lg bg-slate-900 px-4 py-2 text-xs font-semibold text-white shadow-xs hover:bg-slate-800 transition-colors"
        >
          Connect a repository
        </Link>
      </div>
    );
  }

  return (
    <ul className="mt-6 space-y-3">
      {jobs.map((job) => (
        <li
          key={job.id}
          className="rounded-xl border border-slate-200 bg-white p-5 tactile-card transition-all"
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <span className="text-base font-bold text-slate-900">{job.full_name}</span>
              <span
                className={`rounded-md border px-2.5 py-0.5 text-xs font-semibold ${STATUS_STYLE[job.status]}`}
              >
                {STATUS_LABEL[job.status]}
              </span>
            </div>

            <div className="flex items-center gap-2">
              {job.profile_id && (
                <>
                  <button
                    onClick={() => copyLink(job.profile_id)}
                    className="rounded-md border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50 transition-colors cursor-pointer shadow-2xs"
                  >
                    {copiedId === job.profile_id ? "✓ Copied" : "Copy Link"}
                  </button>
                  <Link
                    href={`/p/${job.profile_id}`}
                    className="inline-flex items-center rounded-md bg-slate-900 px-3 py-1 text-xs font-semibold text-white hover:bg-slate-800 transition-colors shadow-2xs"
                  >
                    View Profile
                  </Link>
                </>
              )}
              {job.status !== "revoked" && (
                <button
                  type="button"
                  onClick={() => revoke(job)}
                  disabled={busy === job.id}
                  className="rounded-md px-2.5 py-1 text-xs font-medium text-slate-400 hover:text-rose-600 transition-colors disabled:text-slate-200 cursor-pointer"
                >
                  Revoke
                </button>
              )}
            </div>
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500 font-mono">
            <span>Author: {job.author_email}</span>
            <span>·</span>
            <span>Queued: {new Date(job.created_at).toLocaleDateString()}</span>
          </div>

          {job.reason && (
            <p className="mt-2 text-xs leading-relaxed text-slate-600 bg-slate-50 p-2.5 rounded border border-slate-200/60">
              {job.reason}
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}
