import Link from "next/link";

/**
 * Sits in the `(site)` group, not the root layout: `/p/<id>` carries no product chrome, and
 * a footer is chrome. A recipient reading someone's profile is not browsing a site.
 */
const COLUMNS = [
  {
    heading: "Product",
    links: [
      { href: "/how-it-works", label: "How it works" },
      { href: "/what-we-measure", label: "What it measures" },
      { href: "/connect", label: "Connect a repo" },
    ],
  },
  {
    heading: "Transparency",
    links: [{ href: "/privacy", label: "Privacy" }],
  },
];

export default function Footer() {
  return (
    <footer className="mt-24 border-t border-zinc-200/80 bg-white">
      <div className="mx-auto max-w-6xl px-6 py-12">
        <div className="flex flex-col gap-10 sm:flex-row sm:justify-between">
          <div className="max-w-xs space-y-3">
            <div className="flex items-center gap-2.5">
              <div className="grid grid-cols-2 gap-0.5 rounded-md bg-zinc-900 p-1">
                <div className="h-2 w-2 rounded-[1px] bg-white" />
                <div className="h-2 w-2 rounded-[1px] bg-zinc-400" />
                <div className="h-2 w-2 rounded-[1px] bg-zinc-400" />
                <div className="h-2 w-2 rounded-[1px] bg-white" />
              </div>
              <span className="font-mono text-sm font-bold tracking-tight text-zinc-900">
                vouch
              </span>
            </div>
            <p className="text-xs leading-relaxed text-zinc-600">
              It supports a hiring decision. It does not make one.
            </p>
          </div>

          <div className="flex gap-12 sm:gap-16">
            {COLUMNS.map((col) => (
              <div key={col.heading} className="space-y-3">
                <h2 className="font-mono text-[10px] font-bold uppercase tracking-wider text-zinc-400">
                  {col.heading}
                </h2>
                <ul className="space-y-2">
                  {col.links.map((l) => (
                    <li key={l.href}>
                      <Link
                        href={l.href}
                        className="text-xs font-medium text-zinc-600 transition-colors hover:text-zinc-900"
                      >
                        {l.label}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>

        <p className="mt-10 border-t border-zinc-200/80 pt-6 text-[11px] text-zinc-500">
          Profiles are built from git history you nominate. No overall score is computed, at
          any layer.
        </p>
      </div>
    </footer>
  );
}
