# Frontend

Chat UI for the Agent Workshop. Deployed as a Databricks App.

The browser calls the Agent API directly — this app just serves the static files and provides the API URL.

## Setup

1. Copy `app.yaml.example` to `app.yaml`
2. Update the following values:

| Variable | Description | Where to find it |
|----------|-------------|-------------------|
| `AGENT_API_URL` | URL of the deployed agent-api app | Workspace → Apps → agent-workshop-api → URL |

## Files

| File | Purpose |
|------|---------|
| `main.py` | FastAPI — serves static files + `/api-url` config endpoint |
| `static/index.html` | Chat UI structure |
| `static/styles.css` | All CSS |
| `static/app.js` | JavaScript — streaming, tool blocks, markdown, thread management |
| `requirements.txt` | Minimal dependencies (no AI packages) |
| `app.yaml.example` | Template for app configuration |

## Deploy

```bash
cp app.yaml.example app.yaml
# Edit app.yaml with your agent-api URL

databricks workspace import-dir . /Workspace/Users/<YOU>/agent-workshop-frontend --overwrite
databricks apps deploy agent-workshop \
  --source-code-path /Workspace/Users/<YOU>/agent-workshop-frontend
```
