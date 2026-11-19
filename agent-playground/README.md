# Agent Playground

A Databricks App that chats with every agent you have deployed, similar to the AI Playground but for your own agents. Pick an agent from the header, and each agent keeps its own conversations.

This is a reference app built for this demo repo. It is not a Databricks product feature.

## What it shows

- **Agent discovery.** Every Databricks App named `agent-*` that the signed-in user can access shows up in the picker, the same apps Unity Gateway lists on its Agents tab. Each one is checked to make sure it serves the invocation API.
- **Manual agents.** Anything else (for example a custom LangGraph app or an OpenCode app) is listed in `agents.yml`.
- **One agent API.** Every agent speaks the Agent Bricks invocation API (`POST /api/invocations`, SSE events, human approval), whether or not it's built with Agent Bricks. `check_agent.py` checks an agent against it.
- **Traces per agent.** A **View traces** link opens the MLflow experiment each agent's app declares as a resource.
- **Server-side proxy.** The browser only talks to this app. The app calls agents on the user's behalf.

## Auth model

The app forwards the signed-in user's token to every agent it calls. Databricks Apps adds that token as the `x-forwarded-access-token` header when user authorization is enabled. Agents therefore see the real user: their tools run as that user, and the user only sees agents and apps they can access.

Required user API scopes, set in `databricks.yml`:

| Scope | Why |
|---|---|
| `apps` | List and look up `agent-*` apps as the user. The Apps API rejects tokens without it. |
| `sql` | Agent tools that run SQL as the user, for example the FinOps agent's SQL tool. |
| `ai-gateway` | Model calls made with the user's token. |

Each user consents to these scopes on first visit. If the token is missing, the app returns 401 and does not fall back to its service principal. A fallback would make agents see the playground's identity instead of the user, so the app refuses to run without the token.

## Agents

### `agent-*` apps (discovered)

Any app whose name starts with `agent-` appears automatically: Agent Bricks agents (`agent-bricks-*`) and custom agents alike. Name your agents this way. Unity Gateway uses the same prefix for its Agents tab, and this app is deployed as `multi-agent-playground` so it isn't listed as an agent itself.

The picker marks an agent unavailable when its app isn't running, or when it doesn't serve `/api/invocations`. The playground sends each app an empty invocation request, which makes no model call: an agent rejects it as a bad request (400 or 422), while an app without the route returns 404 or 405.

### `agents.yml` (manual)

```yaml
agents:
  - name: My Custom Agent
    url: https://<your-app>.databricksapps.com
    description: Custom LangGraph agent with Lakebase memory
```

- `name` is required and must be unique. It is shown in the picker.
- `url` is the agent app's URL.
- `description` is optional.

`agents.yml` is for agents that can't follow the `agent-*` naming, such as agents outside this workspace. It ships with no agents. Put workspace-specific URLs in `agents.local.yml`, in the same format. It's gitignored, and the bundle still deploys it with the app.

### Adding a custom agent

A custom agent works in the playground if it:

1. **Serves the invocation API.** `POST /api/invocations` takes `{"id", "session_id", "input": {"messages": [...]}, "stream": true}` and streams `data:` events: `run.started`, then `delta` (text) and `message` (assistant text, tool calls, tool results), then `run.completed` or `run.failed`. It keeps conversation state per `session_id`.
2. **Only needs user scopes the playground has** (`apps`, `sql`, `ai-gateway`). If the agent app asks for any other scope, the playground's forwarded token is rejected with a 401.
3. **Declares its MLflow experiment as an app resource.** The playground reads it from the Apps API and shows a **View traces** link to the experiment's Traces tab. By convention, each agent traces to `/Shared/agents/<agent>`.

Check it before adding it:

```bash
uv run --with databricks-sdk python check_agent.py https://<your-app>.databricksapps.com --profile <profile>
```

It sends two turns as you and checks the event order, that an assistant message comes back, and that the second turn remembers the first.

## Conversations

The playground generates a session ID per conversation and sends it as `session_id`, so the agent keeps the conversation state. The transcript is stored in the browser's local storage, keyed by agent. While a reply is in progress, animated dots show at the bottom of it until the agent's stream ends.

## Approvals

When an agent calls a tool that needs approval, the UI shows the pending call with Approve and Reject buttons. The decision resumes the same session.

## Project files

| File | Purpose |
|---|---|
| `main.py` | FastAPI: discovery, agent resolution, invocation stream translation, static files |
| `static/index.html`, `static/app.js`, `static/styles.css` | Chat UI: agent picker, streaming, tool blocks, approvals |
| `agents.yml` | Manual agent list (ships empty, with commented examples); `agents.local.yml` for workspace URLs |
| `check_agent.py` | Checks that an agent speaks the invocation API |
| `databricks.yml` | Declarative Automation Bundle: app name, source, user API scopes |
| `app.yaml` | Start command |
| `requirements.txt` | Python dependencies |

## Deploy

Requires the Databricks CLI with a profile for your workspace.

```bash
databricks bundle validate -p <profile>
databricks bundle deploy -p <profile>
databricks bundle run agent_playground -p <profile>
```

Open the app URL from the Apps page. Discovery needs the app to run inside Databricks Apps. Running it locally does not work, because there is no forwarded token.

## Limitations

- Discovery and the proxy depend on the forwarded user token. Locally, or in an app without user authorization, the app cannot discover agents.
- Conversation history lives in the browser. Clearing local storage, or using another browser, loses it. The agent still keeps its own session state.
- A pending approval is lost on page reload. The agent stays paused on its session until a new turn is sent.
- Only apps named `agent-*` are discovered automatically. Other agents must be listed in `agents.yml`. The `agent-` prefix is how Unity Gateway's Agents tab appears to pick apps; it isn't documented.
- Agents that do not use the forwarded token act with their own identity. The custom LangGraph agent's SQL tool runs as its service principal, not the signed-in user.
- The picker is a dropdown, not `@` mentions.
