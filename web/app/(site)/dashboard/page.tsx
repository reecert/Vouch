import type { Metadata } from "next";
import { redirect } from "next/navigation";
import Link from "next/link";

import JobList from "@/components/JobList";
import { currentUser } from "@/lib/session";
import CopyCliBox from "../CopyCliBox";

export const metadata: Metadata = { title: "Your Profiles · vouch" };
export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const user = await currentUser();
  if (!user) redirect("/connect");

  return (
    <main className="mx-auto max-w-4xl px-6 py-12 animate-fade-in">
      <header className="rounded-2xl border border-slate-200 bg-white p-8 shadow-xs mb-8 flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-emerald-500" />
            <p className="text-xs font-bold uppercase tracking-wider text-slate-500">
              Account: {user.login}
            </p>
          </div>
          <h1 className="mt-2 text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
            Your Profiles
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-slate-600">
            Each link is a frozen, unlisted document. Share it with screeners or hiring managers. Revoking permanently deletes the document from resolution.
          </p>
        </div>

        <Link
          href="/connect"
          className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2.5 text-xs font-semibold text-white shadow-xs hover:bg-slate-800 transition-all active:scale-[0.98]"
        >
          <span>+ Connect New Repo</span>
        </Link>
      </header>

      <JobList />

      <section className="mt-12 rounded-2xl border border-slate-200 bg-white p-6 tactile-card">
        <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500">
          Corroborating via Local CLI
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-slate-600 max-w-2xl">
          Web profiles analyze git history. Running the local CLI joins your local Claude Code session telemetry against those commits. Session logs remain private on your computer; only the resulting claim locators are uploaded.
        </p>
        <div className="mt-4">
          <CopyCliBox />
        </div>
      </section>
    </main>
  );
}
