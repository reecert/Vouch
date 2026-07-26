# vouch — profile viewer

A read-only viewer for frozen profile snapshots. Next.js (App Router), TypeScript,
Tailwind v4, statically exported.

## Why it is static

A share link resolves to an **immutable snapshot**, not a live query against someone's
activity. Profiles are JSON files under `data/profiles/`, pre-rendered at build time via
`generateStaticParams`. There is no database, no session, and nothing to log in to — which
is also what makes "no login required to view" trivially true rather than a permissions
problem to get right.

## Generate a profile and view it

```sh
# from the repo root
vouch profile <repo-url> --author you@example.com \
    --log-dir ~/.claude/projects \
    --web-dir web/data/profiles

cd web && npm install && npm run dev     # then open the printed /p/<id> link
```

`npm run build` produces a fully static bundle in `out/`, deployable to any static host.

## What the viewer deliberately does not do

- **It computes nothing.** No score, no aggregate, no ranking — not even client-side. If
  the viewer could derive an overall number, the guarantee that the profile carries none
  would be cosmetic.
- **The index page is not a directory.** It lists only the snapshots built into the local
  bundle, for development. A browsable list of everyone profiled is a candidate directory,
  which is an explicit phase-1 non-goal.
- **Declining verdicts are styled neutrally.** "Insufficient evidence" is a normal, frequent
  outcome of an honest profile; rendering it in alarm colours would teach readers to see it
  as a mark against the candidate, which it is not.

## Sample snapshots

The two profiles in `data/profiles/` are generated from **synthetic fixture repos** with a
mock judge (`fixture://example/...`). They exist to exercise the viewer's range — one with
session telemetry, one git-only where planning discipline is `not_assessed`. Nothing in
them describes a real person.
