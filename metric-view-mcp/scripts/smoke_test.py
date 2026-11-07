"""End-to-end check of a deployed metric-view MCP.

  python scripts/smoke_test.py https://<app-url>/mcp --token "$(databricks auth token | jq -r .access_token)" \
    --view <an in-scope metric view> --raw-table <a source table that must be rejected>
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
            check("lists the metric view", view in names, names)

            desc, _ = await call("describe_metric_view", view=view)
            sql = desc["sql_example"]
            res, err = await call("query_metric_views", sql=sql)
            check("runs describe_metric_view's sql_example", res and res["rows"], err)
            if res:
                print("      " + sql.replace("\n", "\n      ") + f"\n      rows: {res['rows'][:3]}")

            for label, query in [
                ("rejects a raw source table", f"SELECT * FROM {raw_table}"),
                ("rejects a raw table hidden in a subquery", f"SELECT * FROM (SELECT * FROM {raw_table}) t"),
                ("rejects writes", f"DROP TABLE {desc['view']}"),
            ]:
                _, err = await call("query_metric_views", sql=query)
                check(label, err is not None, "no error returned")

    print("\nALL CHECKS PASSED" if not failed else f"\n{failed} CHECK(S) FAILED")
    return failed


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("url")
    p.add_argument("--token", required=True)
    p.add_argument("--view", required=True, help="bare name of an in-scope metric view")
    p.add_argument("--raw-table", required=True, help="catalog.schema.table that must be rejected")
    a = p.parse_args()
    raise SystemExit(asyncio.run(main(a.url, a.token, a.view, a.raw_table)))
