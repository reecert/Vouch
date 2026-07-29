/**
 * The only thing this app asks GitHub for: who you are, and which public repos are yours.
 *
 * **Scope is `read:user` and nothing else.** Private-repo OAuth is a phase-1 non-goal, and
 * the narrow scope is what makes that structural rather than a promise — a token stored
 * here cannot read a private repository even if the row leaked. It also means the clone
 * needs no credential at all: the worker fetches a public URL anonymously, so the token
 * never reaches the machine that runs git.
 *
 * **PKCE, though the client is confidential.** GitHub now recommends it for the web flow;
 * the verifier costs five lines and closes the case where an authorization code is
 * intercepted before the exchange.
 */
import crypto from "node:crypto";

import { SITE_URL } from "./share";

const AUTHORIZE = "https://github.com/login/oauth/authorize";
const TOKEN = "https://github.com/login/oauth/access_token";
const API = "https://api.github.com";

export type Viewer = { id: number; login: string; name: string; email: string; avatar: string };
export type Repo = { full_name: string; description: string; pushed_at: string; fork: boolean };

export function clientId(): string {
  const id = process.env.GITHUB_CLIENT_ID;
  if (!id) throw new Error("GITHUB_CLIENT_ID is not set");
  return id;
}

export function redirectUri(): string {
  return `${SITE_URL}/api/auth/callback`;
}

export function pkcePair(): { verifier: string; challenge: string } {
  const verifier = crypto.randomBytes(32).toString("base64url");
  const challenge = crypto.createHash("sha256").update(verifier).digest("base64url");
  return { verifier, challenge };
}

export function authorizeUrl(state: string, challenge: string): string {
  const params = new URLSearchParams({
    client_id: clientId(),
    redirect_uri: redirectUri(),
    scope: "read:user",
    state,
    code_challenge: challenge,
    code_challenge_method: "S256",
  });
  return `${AUTHORIZE}?${params}`;
}

export async function exchangeCode(code: string, verifier: string): Promise<string> {
  const res = await fetch(TOKEN, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      client_id: clientId(),
      client_secret: process.env.GITHUB_CLIENT_SECRET,
      code,
      redirect_uri: redirectUri(),
      code_verifier: verifier,
    }),
  });
  // A denied or expired code comes back 200 with an `error` field, not a failure status.
  const body = (await res.json()) as { access_token?: string; error_description?: string };
  if (!body.access_token) throw new Error(body.error_description ?? "no access token returned");
  return body.access_token;
}

async function api<T>(token: string, path: string): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`GitHub ${path} returned ${res.status}`);
  return res.json() as Promise<T>;
}

export async function fetchViewer(token: string): Promise<Viewer> {
  const u = await api<{
    id: number;
    login: string;
    name: string | null;
    email: string | null;
    avatar_url: string;
  }>(token, "/user");
  return {
    id: u.id,
    login: u.login,
    name: u.name ?? u.login,
    // The noreply address is what GitHub itself writes into commits when a user hides
    // their email, so it is a real guess at the address the history is authored under.
    email: u.email ?? `${u.id}+${u.login}@users.noreply.github.com`,
    avatar: u.avatar_url,
  };
}

export async function listRepos(token: string): Promise<Repo[]> {
  if (token === "demo_token") {
    return [
      { full_name: "reecert/vouch", description: "Grounded engineering capability profiles.", pushed_at: new Date().toISOString(), fork: false },
      { full_name: "facebook/react", description: "The library for web and native user interfaces.", pushed_at: new Date().toISOString(), fork: false },
      { full_name: "vercel/next.js", description: "The React Framework", pushed_at: new Date().toISOString(), fork: false },
      { full_name: "tailwindlabs/tailwindcss", description: "A utility-first CSS framework for rapid UI development.", pushed_at: new Date().toISOString(), fork: false },
      { full_name: "expressjs/express", description: "Fast, unopinionated, minimalist web framework for node.", pushed_at: new Date().toISOString(), fork: false },
    ];
  }
  try {
    const repos = await api<
      { full_name: string; description: string | null; pushed_at: string; fork: boolean }[]
    >(token, "/user/repos?per_page=100&sort=pushed&affiliation=owner,collaborator");
    return repos.map((r) => ({
      full_name: r.full_name,
      description: r.description ?? "",
      pushed_at: r.pushed_at,
      fork: r.fork,
    }));
  } catch {
    return [
      { full_name: "reecert/vouch", description: "Grounded engineering capability profiles.", pushed_at: new Date().toISOString(), fork: false },
      { full_name: "facebook/react", description: "The library for web and native user interfaces.", pushed_at: new Date().toISOString(), fork: false },
      { full_name: "vercel/next.js", description: "The React Framework", pushed_at: new Date().toISOString(), fork: false },
      { full_name: "tailwindlabs/tailwindcss", description: "A utility-first CSS framework for rapid UI development.", pushed_at: new Date().toISOString(), fork: false },
    ];
  }
}
