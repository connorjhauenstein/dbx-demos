# dbx-demos

Databricks demo repository.

## Demos

| Demo | Description |
|---|---|
| [rtm-lakebase-demo](./rtm-lakebase-demo) | Real-time market data pipeline: `Kafka → Spark RTM → Lakebase → {Grafana OSS, Databricks App}` |
| [metric-view-mcp](./metric-view-mcp) | MCP server that exposes only Unity Catalog metric views to agents (Claude, AI Playground, Agent Bricks), runs as the calling user, and deploys as a Databricks App with one bundle |
| [agent-workshop-langgraph](./agent-workshop-langgraph) | Hands-on workshop: LangGraph agent API + chat UI as two Databricks Apps, Lakebase conversation memory, MLflow tracing to a UC Volume or UC tables |
| [agent-workshop-mastra](./agent-workshop-mastra) | TypeScript/Mastra agent as a Databricks App: OTel traces to UC tables, Prompt Registry, code-defined LLM judges, production monitoring, offline eval |
