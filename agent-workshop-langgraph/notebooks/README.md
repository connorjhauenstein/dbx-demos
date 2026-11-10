# Notebooks

Development and observability notebooks for the Agent Workshop.

## Files

| Notebook | Purpose |
|----------|---------|
| `workshop_guide.py` | Step-by-step setup walkthrough — start here |
| `run_agent.py` | Run the deployed agent code with full MLflow trace visibility |

## Setup

Before running `run_agent.py`, update the config variables at the top of the notebook:

| Variable | Description |
|----------|-------------|
| `AGENT_API_WORKSPACE_PATH` | Workspace path where agent-api code is deployed |
| `WAREHOUSE_ID` | Your SQL warehouse ID |

The notebook connects to the same Lakebase database and MLflow experiment as the deployed app.

## Upload to Workspace

```bash
databricks workspace mkdirs /Workspace/Users/<YOU>/agent-workshop-notebooks
databricks workspace import /Workspace/Users/<YOU>/agent-workshop-notebooks/run_agent \
  --file run_agent.py --language PYTHON --format SOURCE --overwrite
databricks workspace import /Workspace/Users/<YOU>/agent-workshop-notebooks/workshop_guide \
  --file workshop_guide.py --language PYTHON --format SOURCE --overwrite
```
