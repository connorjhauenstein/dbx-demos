"""Frontend app — serves the chat UI.

API calls go directly from the browser to the agent-api app URL.
The user is already authenticated via Databricks OAuth in their browser.
"""

import logging
import os

logging.basicConfig(level=logging.INFO)

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

AGENT_API_URL = os.environ.get("AGENT_API_URL", "http://localhost:8001").rstrip("/")

app = FastAPI(title="Agent Workshop")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.get("/api-url")
async def get_api_url():
    """Return the agent API URL so the frontend JS knows where to call."""
    return {"url": AGENT_API_URL}


@app.get("/health")
async def health():
    return {"status": "ok"}
