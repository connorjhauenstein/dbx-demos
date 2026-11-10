import { execFileSync } from 'node:child_process';

// Returns a Databricks bearer token, cached until shortly before expiry.
// - In a Databricks App: OAuth M2M using the injected DATABRICKS_CLIENT_ID/SECRET.
// - Locally: minted from the Databricks CLI (profile via DATABRICKS_PROFILE).
let cached: { token: string; exp: number } | null = null;

async function mintM2M(host: string, id: string, secret: string): Promise<{ token: string; ttlMs: number }> {
  const basic = Buffer.from(`${id}:${secret}`).toString('base64');
  const res = await fetch(`${host.replace(/\/$/, '')}/oidc/v1/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', Authorization: `Basic ${basic}` },
    body: new URLSearchParams({ grant_type: 'client_credentials', scope: 'all-apis' }),
  });
  if (!res.ok) throw new Error(`OAuth M2M token request failed: ${res.status} ${await res.text()}`);
  const j: any = await res.json();
  return { token: j.access_token, ttlMs: (j.expires_in ?? 3600) * 1000 };
}

function mintCLI(): { token: string; ttlMs: number } {
  const profile = process.env.DATABRICKS_PROFILE ?? 'DEFAULT';
  const out = execFileSync('databricks', ['auth', 'token', '-p', profile], {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'ignore'],
  });
  return { token: JSON.parse(out).access_token, ttlMs: 50 * 60 * 1000 };
}

export async function getToken(): Promise<string> {
  const now = Date.now();
  if (cached && cached.exp > now + 60_000) return cached.token;

  const { DATABRICKS_CLIENT_ID, DATABRICKS_CLIENT_SECRET, DATABRICKS_HOST } = process.env;
  const minted =
    DATABRICKS_CLIENT_ID && DATABRICKS_CLIENT_SECRET && DATABRICKS_HOST
      ? await mintM2M(DATABRICKS_HOST, DATABRICKS_CLIENT_ID, DATABRICKS_CLIENT_SECRET)
      : mintCLI();

  cached = { token: minted.token, exp: now + minted.ttlMs };
  return minted.token;
}
