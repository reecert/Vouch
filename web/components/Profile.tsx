/**
 * The report itself.
 *
 * Section order is set for a hiring screener (docs/plan.md open question 1): evidence
 * first so the provenance is a headline rather than an appendix, then the dimension
 * readouts, then **Risks to probe** — because generating the next interview question is
 * the reader's actual job, and burying it under the limitations would waste it.
 *
 * There is no overall score anywhere, and no way to compute one from what is rendered.
 */
import type {
  Claim as ClaimType,
  Confound,
  DimensionFinding,
  DimensionKey,
  Profile,
} from "@/lib/profile";
import {
  CONFIDENCE_LABELS,
  DIMENSION_QUESTIONS,
  DIMENSION_TITLES,
  VERDICT_LABELS,
  VERDICT_STYLES,
  shortSha,
} from "@/lib/profile";

function Section({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="border-t border-slate-200 py-10 dark:border-slate-800">
      <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">
        {title}
      </h2>
      {subtitle ? (
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{subtitle}</p>
      ) : null}
      <div className="mt-5">{children}</div>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className="mt-0.5 text-sm font-medium tabular-nums">{value}</dd>
    </div>
  );
}

function Claim({ claim }: { claim: ClaimType }) {
  return (
    <li className="text-sm leading-relaxed">
      <span>{claim.text}</span>{" "}
      <span className="whitespace-nowrap">
        {claim.locators.map((loc, i) => (
          <code
            key={`${loc.sha}-${loc.path ?? ""}-${i}`}
            className="ml-1 rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300"
          >
            {shortSha(loc.sha)}
            {loc.path ? ` · ${loc.path}` : ""}
          </code>
        ))}
      </span>
    </li>
  );
}

function Finding({ finding }: { finding: DimensionFinding }) {
  const key = finding.dimension as DimensionKey;
  return (
    <article className="rounded-lg border border-slate-200 p-5 dark:border-slate-800">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold">{DIMENSION_TITLES[key] ?? key}</h3>
          <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">
            {DIMENSION_QUESTIONS[key]}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${
              VERDICT_STYLES[finding.verdict]
            }`}
          >
            {VERDICT_LABELS[finding.verdict]}
          </span>
          <span className="text-xs text-slate-500 dark:text-slate-400">
            {CONFIDENCE_LABELS[finding.confidence]}
          </span>
        </div>
      </div>

      <p className="mt-4 text-sm leading-relaxed">{finding.summary}</p>

      {finding.claims.length > 0 ? (
        <ul className="mt-4 space-y-2 border-l-2 border-slate-200 pl-4 dark:border-slate-800">
          {finding.claims.map((claim, i) => (
            <Claim key={i} claim={claim} />
          ))}
        </ul>
      ) : null}

      {finding.limitations.length > 0 ? (
        <ul className="mt-4 space-y-1 text-xs text-slate-500 dark:text-slate-400">
          {finding.limitations.map((lim, i) => (
            <li key={i}>— {lim}</li>
          ))}
        </ul>
      ) : null}
    </article>
  );
}

function ConfoundRow({ confound }: { confound: Confound }) {
  const tone =
    confound.severity === "invalidating"
      ? "text-rose-700 dark:text-rose-300"
      : "text-slate-600 dark:text-slate-300";
  return (
    <li className="text-sm leading-relaxed">
      <span className={`font-medium ${tone}`}>
        {confound.key.replace(/_/g, " ")}
      </span>{" "}
      <span className="text-xs uppercase tracking-wide text-slate-400">
        {confound.direction}
      </span>
      <p className="mt-0.5 text-sm text-slate-600 dark:text-slate-400">{confound.detail}</p>
    </li>
  );
}

export default function ProfileView({ profile }: { profile: Profile }) {
  const ev = profile.evidence_inspected;
  const corr = profile.corroboration;

  return (
    <main className="mx-auto max-w-3xl px-6 py-14">
      <header>
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">
          Engineering capability profile
        </p>
        <h1 className="mt-2 text-2xl font-semibold">{profile.subject}</h1>
        <p className="mt-3 max-w-prose text-sm leading-relaxed text-slate-600 dark:text-slate-400">
          Built from a git history{ev.session_telemetry ? " and consented local session telemetry" : ""}.
          It describes observable behaviour and states what it cannot see. It supports a
          hiring decision; it does not make one.
        </p>
      </header>

      <Section
        title="Evidence inspected"
        subtitle="Stated before anything is concluded from it."
      >
        <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
          <Stat label="Repository" value={ev.repo.split("/").slice(-2).join("/")} />
          <Stat
            label="Commits by subject"
            value={`${ev.n_commits_by_subject} of ${ev.n_commits_in_repo}`}
          />
          <Stat
            label="Diffs read"
            value={
              ev.n_diffs_available
                ? `${ev.n_diffs_read} of ${ev.n_diffs_available}`
                : "none"
            }
          />
          <Stat
            label="Active window"
            value={
              ev.window_first && ev.window_last
                ? `${ev.window_first} → ${ev.window_last}`
                : "—"
            }
          />
          <Stat
            label="Measurements"
            value={`${ev.measured_facts} measured, ${ev.withheld_facts} withheld`}
          />
          <Stat
            label="Sessions"
            value={ev.session_telemetry ? String(ev.n_sessions) : "not collected"}
          />
          <Stat label="Head" value={shortSha(ev.head_sha)} />
          <Stat
            label="Excluded files"
            value={
              Object.keys(ev.excluded_paths).length
                ? Object.entries(ev.excluded_paths)
                    .map(([k, v]) => `${v} ${k}`)
                    .join(", ")
                : "none"
            }
          />
        </dl>
      </Section>

      <Section title="Dimensions" subtitle="Reported side by side. There is no overall score.">
        <div className="space-y-4">
          {profile.findings.map((finding) => (
            <Finding key={finding.dimension} finding={finding} />
          ))}
        </div>
      </Section>

      <Section
        title="Risks to probe"
        subtitle="What this evidence could not settle — ask about these."
      >
        <ol className="space-y-3">
          {profile.risks_to_probe.map((risk, i) => (
            <li key={i} className="flex gap-3 text-sm leading-relaxed">
              <span className="mt-0.5 shrink-0 font-mono text-xs text-slate-400">
                {String(i + 1).padStart(2, "0")}
              </span>
              <span>{risk}</span>
            </li>
          ))}
        </ol>
      </Section>

      <Section
        title="Corroboration"
        subtitle="Which claims have a second source behind them."
      >
        {corr.ran ? (
          <p className="text-sm leading-relaxed">
            <span className="font-medium tabular-nums">
              {corr.n_corroborated} of {corr.n_commits}
            </span>{" "}
            commits have session evidence behind them
            {corr.n_ambiguous > 0 ? `, ${corr.n_ambiguous} ambiguous` : ""}.
            Uncorroborated means no session was recorded for that work — not that the work
            was unsupervised.
          </p>
        ) : (
          <p className="text-sm leading-relaxed text-slate-600 dark:text-slate-400">
            Commits were not correlated with session activity, so no claim in this profile
            is corroborated by a second source.
          </p>
        )}
      </Section>

      {profile.confounds.length > 0 ? (
        <Section
          title="What could make these readings wrong"
          subtitle="Detected in the history itself, before any judgement was formed."
        >
          <ul className="space-y-4">
            {profile.confounds.map((c) => (
              <ConfoundRow key={c.key} confound={c} />
            ))}
          </ul>
        </Section>
      ) : null}

      <Section title="Limitations" subtitle="What this profile cannot see.">
        <ul className="space-y-2">
          {profile.limitations.map((lim, i) => (
            <li
              key={i}
              className="text-sm leading-relaxed text-slate-600 dark:text-slate-400"
            >
              — {lim}
            </li>
          ))}
        </ul>
      </Section>

      <footer className="border-t border-slate-200 py-8 text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
        <p>
          Frozen snapshot <code className="font-mono">{profile.profile_id}</code>
          {profile.provenance.judge_model
            ? ` · judged by ${profile.provenance.judge_model}`
            : ""}
          {profile.provenance.prompt_version
            ? ` · prompt ${profile.provenance.prompt_version}`
            : ""}
        </p>
        {profile.provenance.downgrades.length > 0 ? (
          <p className="mt-2">
            {profile.provenance.downgrades.length} verdict(s) were downgraded by the
            evidence check after the model answered.
          </p>
        ) : null}
      </footer>
    </main>
  );
}
