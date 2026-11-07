import uuid
import requests
from config import LINEAR_API_KEY, LINEAR_TEAM_ID


def create_issue(title: str, description: str) -> str:
    if not LINEAR_API_KEY:
        fake_id = f"STUB-{uuid.uuid4().hex[:6].upper()}"
        print(f"[LINEAR STUB] Would create: {title!r} → {fake_id}")
        return fake_id

    resp = requests.post(
        "https://api.linear.app/graphql",
        headers={"Authorization": LINEAR_API_KEY, "Content-Type": "application/json"},
        json={"query": """
            mutation CreateIssue($title: String!, $description: String!, $teamId: String!) {
              issueCreate(input: {title: $title, description: $description, teamId: $teamId}) {
                issue { id identifier }
              }
            }
        """, "variables": {"title": title, "description": description, "teamId": LINEAR_TEAM_ID}},
        timeout=10,
    )
    return resp.json()["data"]["issueCreate"]["issue"]["identifier"]
