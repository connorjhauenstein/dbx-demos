import { Agent } from '@mastra/core/agent';
import { createOpenAICompatible } from '@ai-sdk/openai-compatible';

// Build the chat agent. The Databricks bearer token is injected per-request via a
// custom fetch (rather than a fixed apiKey) so a long-running server always uses a
// fresh token — CLI-minted locally, OAuth M2M inside a Databricks App.
export function createChatAgent(getToken: () => Promise<string>, instructions: string): Agent {
  const databricks = createOpenAICompatible({
    name: 'databricks',
    baseURL: `${(process.env.DATABRICKS_HOST ?? '').replace(/\/$/, '')}/serving-endpoints`,
    apiKey: 'injected-per-request',
    fetch: (async (input: any, init: any = {}) => {
      const token = await getToken();
      const headers = new Headers(init.headers as HeadersInit | undefined);
      headers.set('Authorization', `Bearer ${token}`);
      return fetch(input, { ...init, headers });
    }) as typeof fetch,
  });

  return new Agent({
    name: 'chat-agent',
    instructions,
    model: databricks(process.env.DATABRICKS_MODEL ?? 'databricks-claude-sonnet-4-6'),
  });
}
