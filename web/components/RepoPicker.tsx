"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

type Repo = { full_name: string; description: string; pushed_at: string; fork: boolean };

// Suggestions for the custom-repo field only. Never shown as "your repositories".
const PRESETS = [
  "reecert/vouch",
  "facebook/react",
  "vercel/next.js",
  "tailwindlabs/tailwindcss",
  "expressjs/express",
];

/**
 * A pasted GitHub link, reduced to the `owner/repo` the API accepts.
 *
 * Convenience, not validation: `/api/jobs` is the only thing that decides whether a name is
 * safe to hand `git clone`, and its pattern is pinned against `vouch/serve/db.py` by a
 * test. A second copy of that regex here would be a fourth transcription with no test
 * behind it, so the server's refusal is what the user sees.
 */
function parseRepoInput(input: string): string {
  const withoutHost = input.trim().replace(/\.git$/, "").split("github.com/").pop() ?? "";
  return withoutHost.replace(/^\/+|\/+$/g, "");
}

export default function RepoPicker({ defaultEmail }: { defaultEmail: string }) {
  const router = useRouter();
  const [mode, setMode] = useState<"list" | "custom">("list");
  const [repos, setRepos] = useState<Repo[] | null>(null);
  const [selected, setSelected] = useState("");
  const [customInput, setCustomInput] = useState("");
  const [email, setEmail] = useState(defaultEmail);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch("/api/repos")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("Could not fetch repositories"))))
      .then((d: { repos: Repo[] }) => {
        setRepos(d.repos);
        if (d.repos.length > 0 && d.repos[0]) {
          setSelected(d.repos[0].full_name);
        }
      })
      // A plausible list is worse than an empty one: it is indistinguishable from the real
      // account's, and the user would queue a run against a repo they never picked.
      .catch(() => {
        setRepos([]);
        setError("Your repositories could not be loaded. Enter one by name instead.");
      });
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const repoToSubmit = mode === "list" ? selected : parseRepoInput(customInput);

    if (!repoToSubmit) {
      setError("Please select or enter a valid repository (owner/repository).");
      return;
    }
    if (!email || !email.includes("@")) {
      setError("Please enter a valid Git author email address.");
      return;
    }

    setBusy(true);
    setError("");

    try {
      const res = await fetch("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ full_name: repoToSubmit, author_email: email }),
      });
      if (res.ok) {
        router.push("/dashboard");
        return;
      }
      const body = (await res.json().catch(() => ({}))) as { error?: string };
      setError(body.error ?? "The job could not be queued.");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to connect repository.");
    } finally {
      setBusy(false);
    }
  }

  const shown = (repos ?? []).filter((r) =>
    r.full_name.toLowerCase().includes(filter.toLowerCase())
  );

  return (
    <form
      onSubmit={submit}
      className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm tactile-card transition-all"
    >
      <div className="mb-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-100 pb-4">
        <div>
          <h2 className="text-base font-bold text-slate-900">Step 1: Choose a Repository</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Select from your account or enter any public GitHub repository.
          </p>
        </div>
        <div className="flex rounded-xl bg-slate-100 p-1 border border-slate-200/80">
          <button
            type="button"
            onClick={() => setMode("list")}
            className={`rounded-lg px-3.5 py-1.5 text-xs font-semibold transition-all ${
              mode === "list"
                ? "bg-white text-slate-900 shadow-xs"
                : "text-slate-600 hover:text-slate-900"
            }`}
          >
            Your Repositories
          </button>
          <button
            type="button"
            onClick={() => {
              setMode("custom");
              if (!customInput && selected) setCustomInput(selected);
            }}
            className={`rounded-lg px-3.5 py-1.5 text-xs font-semibold transition-all ${
              mode === "custom"
                ? "bg-white text-slate-900 shadow-xs"
                : "text-slate-600 hover:text-slate-900"
            }`}
          >
            Any Public Repo
          </button>
        </div>
      </div>

      {mode === "list" ? (
        <div>
          <div className="flex items-center justify-between gap-2">
            <label className="text-xs font-bold uppercase tracking-wider text-slate-500" htmlFor="filter">
              Filter repositories
            </label>
            <span className="text-xs font-medium text-slate-500">
              {shown.length} {shown.length === 1 ? "repo" : "repos"} available
            </span>
          </div>

          <div className="relative mt-2">
            <input
              id="filter"
              type="search"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Search repositories by name..."
              className="w-full rounded-xl border border-slate-200 bg-slate-50/70 px-3.5 py-2.5 text-sm text-slate-900 placeholder:text-slate-400 focus:border-slate-900 focus:bg-white focus:outline-none transition-colors"
            />
            {filter && (
              <button
                type="button"
                onClick={() => setFilter("")}
                className="absolute right-3 top-2.5 text-xs text-slate-400 hover:text-slate-600"
              >
                Clear
              </button>
            )}
          </div>

          {repos === null ? (
            <div className="mt-3 flex items-center justify-center gap-3 rounded-xl border border-slate-100 bg-slate-50/50 p-8">
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-slate-900 border-t-transparent" />
              <span className="text-sm font-medium text-slate-600">Loading repositories...</span>
            </div>
          ) : (
            <ul className="mt-3 max-h-72 divide-y divide-slate-100 overflow-y-auto rounded-xl border border-slate-200 bg-white shadow-2xs">
              {shown.length === 0 && (
                <li className="px-4 py-8 text-center text-sm text-slate-500">
                  <p>No matching repositories found.</p>
                  <button
                    type="button"
                    onClick={() => setMode("custom")}
                    className="mt-2 text-xs font-semibold text-slate-900 underline hover:text-slate-700"
                  >
                    Enter custom repository name →
                  </button>
                </li>
              )}
              {shown.map((repo) => {
                const isChecked = selected === repo.full_name;
                return (
                  <li key={repo.full_name}>
                    <label
                      className={`flex cursor-pointer items-start gap-x-3 px-4 py-3 transition-colors ${
                        isChecked ? "bg-slate-50 font-medium" : "hover:bg-slate-50/60"
                      }`}
                    >
                      <input
                        type="radio"
                        name="repo"
                        value={repo.full_name}
                        checked={isChecked}
                        onChange={() => setSelected(repo.full_name)}
                        className="mt-1 accent-slate-900"
                      />
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center gap-2 text-sm text-slate-900">
                          <span className="font-semibold">{repo.full_name}</span>
                          {repo.fork && (
                            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] uppercase font-mono text-slate-500">
                              fork
                            </span>
                          )}
                        </span>
                        {repo.description && (
                          <span className="block truncate text-xs text-slate-500 mt-0.5">
                            {repo.description}
                          </span>
                        )}
                      </span>
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      ) : (
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-bold uppercase tracking-wider text-slate-500" htmlFor="customRepo">
              Repository Name or GitHub URL
            </label>
            <p className="mt-1 text-xs text-slate-600">
              Enter any public repository in <code className="font-mono bg-slate-100 px-1.5 py-0.5 rounded border border-slate-200 text-slate-800">owner/repository</code> format or paste its GitHub link.
            </p>
            <input
              id="customRepo"
              type="text"
              value={customInput}
              onChange={(e) => setCustomInput(e.target.value)}
              placeholder="e.g. facebook/react or https://github.com/facebook/react"
              className="mt-2 w-full rounded-xl border border-slate-200 bg-slate-50/70 px-3.5 py-2.5 text-sm text-slate-900 placeholder:text-slate-400 focus:border-slate-900 focus:bg-white focus:outline-none transition-colors"
            />
          </div>

          <div>
            <span className="text-xs font-semibold text-slate-500">Popular presets:</span>
            <div className="mt-2 flex flex-wrap gap-2">
              {PRESETS.map((preset) => (
                <button
                  key={preset}
                  type="button"
                  onClick={() => setCustomInput(preset)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100 hover:text-slate-900 transition-colors"
                >
                  <span className="font-mono">{preset}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      <div className="mt-8 pt-6 border-t border-slate-100">
        <label className="block text-base font-bold text-slate-900" htmlFor="email">
          Step 2: Git Author Email
        </label>
        <p className="mt-1 text-xs text-slate-600 leading-relaxed">
          Must match the address used to author commits in <code className="font-mono bg-slate-100 px-1.5 py-0.5 rounded border border-slate-200 text-slate-800">git log</code>.
        </p>
        <div className="relative mt-2.5">
          <input
            id="email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            className="w-full rounded-xl border border-slate-200 bg-slate-50/70 px-3.5 py-2.5 text-sm text-slate-900 placeholder:text-slate-400 focus:border-slate-900 focus:bg-white focus:outline-none transition-colors"
          />
        </div>
      </div>

      {error && (
        <div className="mt-6 rounded-xl border border-rose-200 bg-rose-50/80 p-3.5 text-xs text-rose-800 font-medium flex items-center gap-2">
          <span>⚠️</span>
          <span>{error}</span>
        </div>
      )}

      <div className="mt-8 flex flex-col sm:flex-row sm:items-center justify-between gap-4 pt-6 border-t border-slate-100">
        <div className="text-xs text-slate-500 font-medium">
          Target:{" "}
          <span className="font-semibold font-mono text-slate-800">
            {mode === "list" ? selected || "None selected" : parseRepoInput(customInput) || "None entered"}
          </span>
        </div>
        <button
          type="submit"
          disabled={busy || (mode === "list" ? !selected : !customInput.trim())}
          className="inline-flex items-center justify-center gap-2 rounded-xl bg-slate-900 px-6 py-3 text-sm font-semibold text-white shadow-xs hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300 transition-all active:scale-[0.98]"
        >
          {busy && <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />}
          <span>{busy ? "Queueing Analysis…" : "Generate Capability Profile"}</span>
        </button>
      </div>
    </form>
  );
}
