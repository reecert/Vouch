import Link from "next/link";
import { currentUser } from "@/lib/session";

const LINKS = [
  { href: "/how-it-works", label: "How it works" },
  { href: "/what-we-measure", label: "What it measures" },
  { href: "/privacy", label: "Privacy" },
];

export default async function Nav() {
  const user = await currentUser();

  return (
    <>
      {/* Tero-style Announcement Bar */}
      <div className="bg-zinc-900 px-4 py-2 text-center text-xs font-medium text-zinc-300 border-b border-zinc-800">
        <Link href="/how-it-works" className="inline-flex items-center gap-2 hover:text-white transition-colors">
          <span className="rounded bg-zinc-800 px-1.5 py-0.5 font-mono text-[10px] font-bold text-zinc-200 border border-zinc-700">
            NEW
          </span>
          <span>Vouch 1.0 — Grounded Engineering Capability Profiles</span>
          <span className="text-zinc-500 font-mono">→</span>
        </Link>
      </div>

      {/* Main Glass Nav */}
      <header className="sticky top-0 z-40 border-b border-zinc-200/80 glass-nav">
        <nav className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3.5">
          <div className="flex items-center gap-x-8">
            <Link href="/" className="group flex items-center gap-2.5">
              {/* Tero-style Grid Logo Mark */}
              <div className="grid grid-cols-2 gap-0.5 p-1 bg-zinc-900 rounded-md shadow-xs group-hover:bg-zinc-800 transition-colors">
                <div className="h-2 w-2 bg-white rounded-[1px]" />
                <div className="h-2 w-2 bg-zinc-400 rounded-[1px]" />
                <div className="h-2 w-2 bg-zinc-400 rounded-[1px]" />
                <div className="h-2 w-2 bg-white rounded-[1px]" />
              </div>
              <span className="text-sm font-bold tracking-tight text-zinc-900 group-hover:text-zinc-700 transition-colors font-mono">
                vouch
              </span>
            </Link>

            <div className="hidden gap-x-6 sm:flex">
              {LINKS.map((l) => (
                <Link
                  key={l.href}
                  href={l.href}
                  className="text-xs font-medium text-zinc-600 hover:text-zinc-900 transition-colors"
                >
                  {l.label}
                </Link>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-x-4">
            {user ? (
              <div className="flex items-center gap-3">
                <Link
                  href="/dashboard"
                  className="text-xs font-semibold text-zinc-800 hover:text-zinc-900 transition-colors"
                >
                  Your profiles
                </Link>
                <div className="h-3.5 w-px bg-zinc-200" />
                <form action="/api/auth/logout" method="post">
                  <button
                    type="submit"
                    className="text-xs font-medium text-zinc-500 hover:text-zinc-900 transition-colors cursor-pointer"
                  >
                    Sign out
                  </button>
                </form>
              </div>
            ) : (
              <Link
                href="/connect"
                className="inline-flex items-center rounded-lg bg-zinc-900 px-3.5 py-1.5 text-xs font-semibold text-white shadow-2xs hover:bg-zinc-800 transition-all active:scale-[0.98]"
              >
                Connect a repo
              </Link>
            )}
          </div>
        </nav>
      </header>
    </>
  );
}
