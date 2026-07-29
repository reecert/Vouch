import type { Metadata } from "next";
import Link from "next/link";
import Image from "next/image";

import RepoPicker from "@/components/RepoPicker";
import { currentUser } from "@/lib/session";

export const metadata: Metadata = { title: "Connect a Repository" };
export const dynamic = "force-dynamic";

export default async function ConnectPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const user = await currentUser();
  const { error } = await searchParams;

  return (
    <main className="mx-auto max-w-4xl px-6 py-12 animate-fade-in">
      <header className="rounded-2xl border border-slate-200 bg-white p-8 shadow-xs mb-8 tactile-card">
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center rounded-md bg-slate-900 px-2.5 py-0.5 text-xs font-mono font-bold text-white">
            VOUCH ANALYSIS
          </span>
          <span className="text-xs font-medium text-slate-500">• Public History Inspection</span>
        </div>

        <h1 className="mt-3 text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
          Connect a Repository
        </h1>

        <p className="mt-3 max-w-2xl text-sm leading-relaxed text-slate-600">
          Vouch analyzes public git commit histories to produce grounded capability profiles.
          Dimensions requiring local session logs will state{" "}
          <code className="font-mono bg-slate-100 text-slate-800 px-1.5 py-0.5 rounded border border-slate-200">
            not collected
          </code>{" "}
          because servers cannot access your local device — see{" "}
          <Link
            href="/how-it-works"
            className="font-semibold text-slate-900 underline underline-offset-4 hover:text-slate-700"
          >
            How it works
          </Link>{" "}
          for local CLI corroboration.
        </p>
      </header>

      {error && (
        <div className="mb-6 rounded-2xl border border-rose-200 bg-rose-50/90 p-4 text-sm text-rose-900 font-medium flex items-start gap-3 shadow-xs">
          <span className="text-base">⚠️</span>
          <div className="flex-1">
            <p className="font-bold text-rose-950">Authentication Notice</p>
            <p className="mt-0.5 text-xs text-rose-800 leading-relaxed">{error}</p>
          </div>
        </div>
      )}

      {user ? (
        <section className="space-y-6">
          {/* User Account Context Banner */}
          <div className="flex items-center justify-between gap-4 rounded-2xl border border-slate-200 bg-white p-4 px-6 shadow-2xs">
            <div className="flex items-center gap-3">
              {user.avatar_url ? (
                <Image
                  src={user.avatar_url}
                  alt={user.login}
                  width={36}
                  height={36}
                  className="rounded-full border border-slate-200"
                />
              ) : (
                <div className="h-9 w-9 rounded-full bg-slate-900 flex items-center justify-center font-bold text-white text-xs">
                  {user.login[0]?.toUpperCase() ?? "U"}
                </div>
              )}
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-bold text-slate-900">{user.name || user.login}</span>
                  <span className="font-mono text-xs text-slate-500">(@{user.login})</span>
                </div>
                <span className="text-xs text-slate-500">{user.email}</span>
              </div>
            </div>

            <form action="/api/auth/logout" method="post">
              <button
                type="submit"
                className="text-xs font-semibold text-slate-500 hover:text-slate-900 transition-colors"
              >
                Sign out
              </button>
            </form>
          </div>

          <RepoPicker defaultEmail={user.email} />
        </section>
      ) : (
        <section className="space-y-6">
          <div className="rounded-2xl border border-slate-200 bg-white p-8 shadow-xs tactile-card">
            <div className="flex flex-col items-start gap-5">
              <div>
                <h2 className="text-xl font-bold text-slate-900">Sign in to start analysis</h2>
                <p className="mt-1.5 text-sm text-slate-600 leading-relaxed max-w-xl">
                  Sign-in only requests minimal read access (<code className="font-mono text-slate-800 font-semibold">read:user</code>). Vouch cannot read private repositories, cannot write to your account, and does not retain credentials.
                </p>
              </div>

              <div className="flex flex-wrap items-center gap-3">
                <a
                  href="/api/auth/github"
                  className="inline-flex items-center gap-2.5 rounded-xl bg-slate-900 px-5 py-3 text-sm font-semibold text-white shadow-xs hover:bg-slate-800 transition-all active:scale-[0.98]"
                >
                  <svg className="h-5 w-5 fill-current" viewBox="0 0 24 24">
                    <path
                      fillRule="evenodd"
                      clipRule="evenodd"
                      d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"
                    />
                  </svg>
                  <span>Sign in with GitHub</span>
                </a>

                <a
                  href="/api/auth/demo"
                  className="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm font-semibold text-slate-800 shadow-2xs hover:bg-slate-50 transition-all"
                >
                  <span className="font-mono text-xs text-slate-500">⚡</span>
                  <span>Quick Dev / Demo Sign-in</span>
                </a>
              </div>
            </div>
          </div>
        </section>
      )}
    </main>
  );
}
