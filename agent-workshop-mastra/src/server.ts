import 'dotenv/config';
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { readFile } from 'node:fs/promises';
import { join, extname, normalize } from 'node:path';
import { getToken } from './auth';
import { createChatAgent } from './mastra/agents/chat-agent';
import { initTracing, traced, flush, SpanType } from './tracing';
import { startPromptRefresh, getPrompt, FALLBACK_PROMPT } from './prompt';
import { computeCost } from './cost';

let agent = createChatAgent(getToken, FALLBACK_PROMPT);
// Databricks Apps inject DATABRICKS_APP_PORT; default to 8000 locally.
const PORT = Number(process.env.DATABRICKS_APP_PORT ?? process.env.PORT ?? 8000);
const PUBLIC_DIR = join(import.meta.dirname, '..', 'public');
const MODEL = process.env.DATABRICKS_MODEL ?? 'databricks-claude-sonnet-4-6';

// Minimal in-memory multi-turn memory (per server lifetime). Persistence (Lakebase)
// is intentionally deferred — the frontend degrades gracefully without it.
type Msg = { role: 'user' | 'assistant'; content: string };
const histories = new Map<string, Msg[]>();

const MIME: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
};

function sendJSON(res: ServerResponse, code: number, obj: unknown) {
  res.writeHead(code, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(obj));
}

async function serveStatic(res: ServerResponse, file: string) {
  try {
    const safe = normalize(file).replace(/^(\.\.[/\\])+/, '');
    const data = await readFile(join(PUBLIC_DIR, safe));
    res.writeHead(200, { 'Content-Type': MIME[extname(safe)] ?? 'application/octet-stream' });
    res.end(data);
  } catch {
    res.writeHead(404);
    res.end('Not found');
  }
}

function readBody(req: IncomingMessage): Promise<any> {
  return new Promise((resolve) => {
    let b = '';
    req.on('data', (c) => (b += c));
    req.on('end', () => {
      try {
        resolve(JSON.parse(b || '{}'));
      } catch {
        resolve({});
      }
    });
  });
}

function buildMessages(threadId: string, message: string): Msg[] {
  return [...(histories.get(threadId) ?? []), { role: 'user', content: message }];
}

async function streamChat(res: ServerResponse, threadId: string, message: string, user?: string) {
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    Connection: 'keep-alive',
    'X-Accel-Buffering': 'no',
  });
  const send = (obj: unknown) => res.write(`data: ${JSON.stringify(obj)}\n\n`);
  const messages = buildMessages(threadId, message);
  let full = '';
  try {
    await traced(
      {
        name: 'chat_turn',
        spanType: SpanType.AGENT,
        inputs: { message },
        attributes: {
          'session.id': threadId,
          'user.id': user,
          'gen_ai.operation.name': 'chat',
          'mlflow.prompt.version': getPrompt().version,
        },
      },
      async (root) => {
        let usage: any = null;
        full = await traced(
          {
            name: 'chat_completion',
            spanType: SpanType.CHAT_MODEL,
            inputs: { messages },
            attributes: { 'gen_ai.request.model': MODEL, 'gen_ai.system': 'databricks' },
          },
          async (llm) => {
            const stream: any = await agent.stream(messages);
            let text = '';
            for await (const chunk of stream.textStream) {
              text += chunk;
              send({ event: 'token', content: chunk });
            }
            usage = await Promise.resolve(stream.usage).catch(() => null);
            const finish = await Promise.resolve(stream.finishReason).catch(() => null);
            if (usage) {
              llm.setAttributes({
                'gen_ai.usage.input_tokens': usage.inputTokens,
                'gen_ai.usage.output_tokens': usage.outputTokens,
                'gen_ai.usage.cached_input_tokens': usage.cachedInputTokens,
                'mlflow.chat.tokenUsage': { input_tokens: usage.inputTokens, output_tokens: usage.outputTokens, total_tokens: usage.totalTokens },
                'mlflow.llm.cost': computeCost(usage.inputTokens, usage.outputTokens),
              });
            }
            if (finish) llm.setAttributes({ 'gen_ai.response.finish_reasons': String(finish) });
            llm.setOutputs({ content: text });
            return text;
          },
        );
        root.setOutputs({ response: full });
        if (usage) {
          root.setAttributes({
            'gen_ai.usage.input_tokens': usage.inputTokens,
            'gen_ai.usage.output_tokens': usage.outputTokens,
            'mlflow.llm.cost': computeCost(usage.inputTokens, usage.outputTokens),
          });
        }
      },
    );
    send({ event: 'done', content: full });
    histories.set(threadId, [...messages, { role: 'assistant', content: full }]);
  } catch (e) {
    send({ event: 'error', detail: String(e) });
  } finally {
    res.end();
    await flush();
  }
}

const server = createServer(async (req, res) => {
  const path = new URL(req.url ?? '/', 'http://localhost').pathname;
  const method = req.method ?? 'GET';
  try {
    if (method === 'GET' && path === '/') return serveStatic(res, 'index.html');
    if (method === 'GET' && path.startsWith('/static/')) return serveStatic(res, path.slice(8));
    if (method === 'GET' && path === '/api-url') return sendJSON(res, 200, { url: '' });
    if (method === 'GET' && path === '/config') return sendJSON(res, 200, { model: MODEL });
    if (method === 'GET' && path === '/health') return sendJSON(res, 200, { status: 'ok' });
    if (method === 'GET' && path === '/threads') return sendJSON(res, 200, { threads: [] });
    if (method === 'GET' && path.startsWith('/history/')) {
      const id = decodeURIComponent(path.slice(9));
      return sendJSON(res, 200, { messages: histories.get(id) ?? [] });
    }
    if (method === 'PATCH' && path.startsWith('/threads/')) return sendJSON(res, 200, { ok: true });
    if (method === 'DELETE' && path.startsWith('/threads/')) {
      histories.delete(decodeURIComponent(path.slice(9)));
      return sendJSON(res, 200, { ok: true });
    }
    if (method === 'POST' && path === '/chat/stream') {
      const { thread_id, message } = await readBody(req);
      const user = (req.headers['x-forwarded-email'] || req.headers['x-forwarded-preferred-username']) as string | undefined;
      return streamChat(res, thread_id ?? 'default', message ?? '', user);
    }
    res.writeHead(404);
    res.end('Not found');
  } catch (e) {
    sendJSON(res, 500, { error: String(e) });
  }
});

await initTracing();
await startPromptRefresh((p) => { agent = createChatAgent(getToken, p.template); });
server.listen(PORT, () => console.log(`agent-workshop-mastra listening on :${PORT}`));
