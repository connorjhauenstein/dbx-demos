import 'dotenv/config';
import { getToken } from './auth';
import { createChatAgent } from './mastra/agents/chat-agent';
import { initTracing, traced, flush, SpanType } from './tracing';
import { fetchPrompt } from './prompt';
import { computeCost } from './cost';

// One-shot CLI runner:  npm run chat -- "your message"
const MODEL = process.env.DATABRICKS_MODEL ?? 'databricks-claude-sonnet-4-6';
await initTracing();
const { template, version } = await fetchPrompt();
const agent = createChatAgent(getToken, template);

const prompt = process.argv.slice(2).join(' ') || 'Hello! Briefly introduce yourself in one sentence.';

const text = await traced(
  {
    name: 'chat_turn',
    spanType: SpanType.AGENT,
    inputs: { message: prompt },
    attributes: { 'session.id': process.env.CHAT_SESSION ?? 'cli', 'gen_ai.operation.name': 'chat', 'mlflow.prompt.version': version },
  },
  async (root) => {
    const t = await traced(
      {
        name: 'chat_completion',
        spanType: SpanType.CHAT_MODEL,
        inputs: { messages: [{ role: 'user', content: prompt }] },
        attributes: { 'gen_ai.request.model': MODEL, 'gen_ai.system': 'databricks' },
      },
      async (llm) => {
        const r: any = await agent.generate(prompt);
        const u = r.usage;
        if (u) {
          llm.setAttributes({
            'gen_ai.usage.input_tokens': u.inputTokens,
            'gen_ai.usage.output_tokens': u.outputTokens,
            'gen_ai.usage.cached_input_tokens': u.cachedInputTokens,
            'mlflow.chat.tokenUsage': { input_tokens: u.inputTokens, output_tokens: u.outputTokens, total_tokens: u.totalTokens },
            'mlflow.llm.cost': computeCost(u.inputTokens, u.outputTokens),
          });
        }
        llm.setOutputs({ content: r.text });
        return r.text as string;
      },
    );
    root.setOutputs({ response: t });
    return t;
  },
);
console.log(text);

await flush();
// Mastra keeps the event loop alive (telemetry/keep-alive handles), so exit explicitly.
process.exit(0);
