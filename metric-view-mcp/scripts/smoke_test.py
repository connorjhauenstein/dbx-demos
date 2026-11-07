"""End-to-end check of a deployed metric-view MCP.

  python scripts/smoke_test.py https://<app-url>/mcp --token "$(databricks auth token -p PROFILE | jq -r .access_token)"
"""

import argparse
import asyncio
import json

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


async def main(url, token, view, raw_table):
    failed = 0

    def check(name, ok, detail=""):
        nonlocal failed
        failed += not ok
        print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"\n      {detail}"))

    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=120) as http:
        async with Client(streamable_http_client(url, http_client=http)) as client:

            async def call(tool, **args):
                r = await client.call_tool(tool, args)
                text = r.content[0].text
                return (None, text) if r.is_error else (json.loads(text), None)

            listed, _ = await call("list_metric_views")
            names = [v["view"].split(".")[-1] for v in listed["metric_views"]]
            print(f"      visible: {names}")
            check("lists metric views only", view in names and "scratch_notes" not in names, names)

            desc, _ = await call("describe_metric_view", view=view)
            measure = desc["measures"][0]["name"]
            dim = next(d["name"] for d in desc["dimensions"] if d["type"] == "string")

            res, err = await call("query_metric", view=view, measures=[measure], dimensions=[dim])
            check("queries a measure by dimension", res and res["rows"], err)
            if res:
                print("      " + res["sql"].replace("\n", "\n      ") + f"\n      rows: {res['rows'][:3]}")

            for label, args in [
                ("rejects a raw source table", {"view": raw_table, "measures": ["x"]}),
                ("rejects a plain table next to the metric views", {"view": "scratch_notes", "measures": ["note"]}),
                ("rejects an invented measure", {"view": view, "measures": ["Revenue"]}),
            ]:
                _, err = await call("query_metric", **args)
                check(label, err is not None, "no error returned")

            res, err = await call("query_metric", view=view, measures=[measure],
                                  filters=[{"dimension": dim, "op": "=", "value": "x' OR 1=1 --"}])
            check("binds filter values (injection matches nothing)", res and res["rows"] == [["0"]], res or err)

    print("\nALL CHECKS PASSED" if not failed else f"\n{failed} CHECK(S) FAILED")
    return failed


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("url")
    p.add_argument("--token", required=True)
    p.add_argument("--view", default="funnel_metrics")
    p.add_argument("--raw-table", default="main.demo_raw.app_events")
    a = p.parse_args()
    raise SystemExit(asyncio.run(main(a.url, a.token, a.view, a.raw_table)))
