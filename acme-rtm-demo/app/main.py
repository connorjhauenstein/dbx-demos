import os
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import queries
import linear_client

app = FastAPI()

@app.get("/api/health")
def health():
    return {"ok": True}

@app.get("/api/alerts")
def get_alerts():
    return queries.open_alerts()

@app.get("/api/diagnosis/{alert_id}")
def get_diagnosis(alert_id: int):
    alert = queries.get_alert(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    history = queries.alert_diagnosis(alert["symbol"], alert["venue"])
    venues = queries.last_seen_per_venue(alert["symbol"])
    return {"history": history, "venues": venues, "alert": alert}

@app.post("/api/alerts/{alert_id}/acknowledge")
def acknowledge(alert_id: int):
    queries.acknowledge(alert_id)
    return {"ok": True}

@app.post("/api/alerts/{alert_id}/oncall")
def notify_oncall(alert_id: int):
    print(f"[ONCALL STUB] Notifying on-call for alert {alert_id}")
    return {"ok": True}

@app.post("/api/alerts/{alert_id}/linear")
def create_ticket(alert_id: int):
    alerts = queries.open_alerts()
    alert = next((a for a in alerts if a["id"] == alert_id), None)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    issue_id = linear_client.create_issue(
        f"Spread widening: {alert['symbol']}",
        f"Delta {(alert.get('our_spread_bps') or 0):.1f} bps vs best competitor "
        f"{(alert.get('best_competitor_bps') or 0):.1f} bps — auto-generated from alert {alert_id}"
    )
    queries.write_linear_id(alert_id, issue_id)
    return {"issue_id": issue_id}

static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("DATABRICKS_APP_PORT", 8000)))
