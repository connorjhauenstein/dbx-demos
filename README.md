# dbx-demos

Databricks demo repository.

## Demos

| Demo | Description |
|---|---|
| [rtm-lakebase-demo](./rtm-lakebase-demo) | Real-time market data pipeline: `Kafka → Spark RTM → Lakebase → {Grafana OSS, Databricks App}` |
| [metric-view-mcp](./metric-view-mcp) | MCP server that exposes only Unity Catalog metric views to agents (Claude, AI Playground, Agent Bricks), runs as the calling user, and deploys as a Databricks App with one bundle |
| [agent-workshop-langgraph](./agent-workshop-langgraph) | Hands-on workshop: LangGraph agent API + chat UI as two Databricks Apps, Lakebase conversation memory, MLflow tracing to a UC Volume or UC tables |
| [agent-workshop-mastra](./agent-workshop-mastra) | TypeScript/Mastra agent as a Databricks App: OTel traces to UC tables, Prompt Registry, code-defined LLM judges, production monitoring, offline eval |
| [genie-agents-as-code](./genie-agents-as-code) | Every Genie agent setting as readable files in git: a template, build to `serialized_space`, explode UI edits back to a reviewable diff, benchmarks shared by data source, offline + SQL tests, and CI gating on the Genie eval API |
| [scheduled-agent-tasks](./scheduled-agent-tasks) | Existing coding agents (Claude Code, Codex, OpenCode) as scheduled Lakeflow Jobs running as a service principal: shared MCPs and skills deployed to Unity Gateway as code, tasks that reference them by name, a job that runs a task with every agent side by side, an MLflow experiment per task with traces in Unity Catalog, and cost per run from tagged gateway usage and billing |
