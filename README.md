# dbx-demos

Databricks demo repository.

## Demos

| Demo | Description |
|---|---|
| [rtm-lakebase-demo](./rtm-lakebase-demo) | Real-time market data pipeline: `Kafka → Spark RTM → Lakebase → {Grafana OSS, Databricks App}` |
| [metric-view-mcp](./metric-view-mcp) | MCP server that exposes only Unity Catalog metric views to agents (Claude, AI Playground, Agent Bricks), runs as the calling user, and deploys as a Databricks App with one bundle |
| [agent-workshop-mastra](./agent-workshop-mastra) | TypeScript/Mastra agent as a Databricks App: OTel traces to UC tables, Prompt Registry, code-defined LLM judges, production monitoring, offline eval |
| [genie-agents-as-code](./genie-agents-as-code) | Every Genie agent setting as readable files in git: a template, build to `serialized_space`, explode UI edits back to a reviewable diff, benchmarks shared by data source, offline + SQL tests, and CI gating on the Genie eval API |

## Ways to build an agent

The same FinOps agent (cost questions over `system.billing.usage`) built four ways. All four use Unity Gateway for models and MCPs, MLflow traces in Unity Catalog, and Unity Catalog permissions.

| Demo | Approach | Runs on |
|---|---|---|
| [agentbricks-langgraph](./agentbricks-langgraph) | **Agent Bricks:** a prompt and three CLI commands give a deployed agent with managed memory, sessions, tracing, and approvals; tools act as the user | Agent Runtime |
| [custom-langgraph](./custom-langgraph) | **Your own framework code:** LangGraph with an in-code tool, Lakebase memory you manage, and your own server, still speaking the Agent Bricks invocation API | Databricks Apps |
| [custom-opencode-agent](./custom-opencode-agent) | **An open-source harness, interactive:** OpenCode configured with a prompt, model, and MCPs instead of agent code, behind the same invocation API | Databricks Apps |
| [scheduled-agent-tasks](./scheduled-agent-tasks) | **A harness, headless:** Claude Code or OpenCode on a schedule as a service principal, with a governed Slack tool and cost per run (job compute, model, SQL warehouse) | Lakeflow Jobs |
| [agent-playground](./agent-playground) | **One chat over all of them:** discovers Agent Bricks agents, lists custom agents from config, forwards the user's identity, and checks agents against the invocation API | Databricks Apps |
