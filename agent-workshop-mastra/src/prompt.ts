import { getToken } from './auth';

// Loads the system prompt from the MLflow (UC) Prompt Registry by alias, so the
// prompt can be versioned and rolled out by moving the alias — no code deploy.
const HOST = (process.env.DATABRICKS_HOST ?? '').replace(/\/$/, '');
const NAME = process.env.MLFLOW_PROMPT_NAME ?? '';
const ALIAS = process.env.MLFLOW_PROMPT_ALIAS ?? 'production';
export const FALLBACK_PROMPT =
  'You are a helpful assistant for the Databricks agent workshop. Be concise, accurate, and friendly.';

let cached: { template: string; version: string } = { template: FALLBACK_PROMPT, version: '0' };

export function getPrompt() {
  return cached;
}

export async function fetchPrompt(): Promise<{ template: string; version: string }> {
  if (!HOST) return cached;
  try {
    const token = await getToken();
    const url = `${HOST}/api/2.0/mlflow/unity-catalog/prompts/${NAME}/versions/by-alias/${ALIAS}`;
    const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data: any = await res.json();
    let template = data.template;
    try { template = JSON.parse(template); } catch { /* already plain text */ }
    cached = { template, version: String(data.version) };
    return cached;
  } catch (e) {
    console.error('[prompt] fetch failed; using cached/fallback:', String(e));
    return cached;
  }
}

// Fetch now, then poll; invoke onChange whenever the resolved version changes
// (e.g., the alias was moved to a new prompt version).
export async function startPromptRefresh(
  onChange: (p: { template: string; version: string }) => void,
  intervalMs = 5 * 60 * 1000,
) {
  const initial = await fetchPrompt();
  onChange(initial);
  console.log(`[prompt] loaded ${NAME}@${ALIAS} v${initial.version}`);
  const timer = setInterval(async () => {
    const prev = cached.version;
    const p = await fetchPrompt();
    if (p.version !== prev) {
      console.log(`[prompt] alias moved → v${p.version}`);
      onChange(p);
    }
  }, intervalMs);
  (timer as any).unref?.();
}
