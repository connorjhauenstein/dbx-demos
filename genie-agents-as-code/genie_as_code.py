"""Manage Genie agents as readable files.

  python genie_as_code.py build --schema main.genie_as_code       files -> .build/<agent>.geniespace.json
  python genie_as_code.py explode growth --schema main.genie_as_code  live agent -> files
  python genie_as_code.py evaluate                                 run every agent's benchmarks

`{schema}` in the files stands for <catalog>.<schema>. Benchmarks in benchmarks/ are added to
every agent that uses the benchmark's metric view.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml
from databricks.sdk import WorkspaceClient

ROOT = Path(__file__).resolve().parent
AGENTS = ROOT / "agents"
BENCHMARKS = ROOT / "benchmarks"
BUILD = ROOT / ".build"
TOKEN = "{schema}"


class Dumper(yaml.SafeDumper):
    """Writes YAML the way people do: indented lists, double quotes, `|` blocks for SQL."""

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


def _str(dumper, s):
    style = "|" if "\n" in s else ('"' if s.startswith("{") else None)
    return dumper.represent_scalar("tag:yaml.org,2002:str", s, style=style)


Dumper.add_representer(str, _str)


def uid(*parts):
    return hashlib.md5(":".join(parts).encode()).hexdigest()


def to_lines(text):
    rows = text.strip().split("\n")
    return [r + "\n" for r in rows[:-1]] + rows[-1:]


def from_lines(rows):
    return "".join(rows).strip()


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower())[:60].strip("_")


def dump_yaml(path, data):
    path.write_text(yaml.dump(data, Dumper=Dumper, sort_keys=False, allow_unicode=True, width=1000))


def load_benchmarks():
    return {p: yaml.safe_load(p.read_text()) for p in sorted(BENCHMARKS.glob("*.yml"))}


def read_example(path):
    first, _, sql = path.read_text().partition("\n")
    return first.replace("-- question:", "", 1).strip(), sql.strip()


def build_spec(agent, schema):
    folder = AGENTS / agent
    cfg = yaml.safe_load((folder / "agent.yml").read_text())
    views = cfg["metric_views"]
    examples = [read_example(p) for p in sorted((folder / "examples").glob("*.sql"))]
    benchmarks = [q for b in load_benchmarks().values() if b["metric_view"] in views for q in b["questions"]]
    spec = {
        "version": 2,
        "config": {"sample_questions": [{"id": uid("sample", q), "question": [q]} for q in cfg["sample_questions"]]},
        # Genie stores metric views under data_sources.tables.
        "data_sources": {"tables": [{"identifier": v} for v in views]},
        "instructions": {
            "text_instructions": [{"id": uid("instructions"), "content": to_lines((folder / "instructions.md").read_text())}],
            "example_question_sqls": [{"id": uid("example", q), "question": [q], "sql": to_lines(sql)} for q, sql in examples],
        },
        "benchmarks": {
            "questions": [
                {"id": uid("benchmark", b["name"]), "question": [b["question"]],
                 "answer": [{"format": "SQL", "content": to_lines(b["sql"])}]}
                for b in benchmarks
            ]
        },
    }
    spec = json.loads(json.dumps(spec).replace(TOKEN, schema))
    # The API rejects collections that aren't sorted by id / identifier.
    spec["data_sources"]["tables"].sort(key=lambda v: v["identifier"])
    for items in (spec["config"]["sample_questions"], spec["instructions"]["example_question_sqls"],
                  spec["benchmarks"]["questions"]):
        items.sort(key=lambda i: i["id"])
    return spec


def build(schema):
    BUILD.mkdir(exist_ok=True)
    for folder in sorted(p for p in AGENTS.iterdir() if p.is_dir()):
        out = BUILD / f"{folder.name}.geniespace.json"
        out.write_text(json.dumps(build_spec(folder.name, schema), indent=2) + "\n")
        print(f"built {out.relative_to(ROOT)}")


def space_ids():
    out = subprocess.run(["databricks", "bundle", "summary", "-o", "json"], cwd=ROOT,
                         check=True, capture_output=True, text=True).stdout
    return {k: v["id"] for k, v in json.loads(out)["resources"]["genie_spaces"].items()}


def fetch(w, space_id):
    space = w.api_client.do("GET", f"/api/2.0/genie/spaces/{space_id}", query={"include_serialized_space": "true"})
    return json.loads(space["serialized_space"])


def keep_order(new, old):
    """Existing items keep their file order; new items go last."""
    return [x for x in old if x in new] + [x for x in new if x not in old]


def canon(o):
    """Compare specs ignoring ids and list order."""
    if isinstance(o, dict):
        return {k: canon(v) for k, v in o.items() if k != "id"}
    if isinstance(o, list):
        items = [canon(v) for v in o]
        return sorted(items, key=json.dumps) if all(isinstance(i, dict) for i in items) else items
    return o


def explode(agent, schema):
    live_raw = fetch(WorkspaceClient(), space_ids()[agent])
    live = json.loads(json.dumps(live_raw).replace(schema, TOKEN))
    folder = AGENTS / agent
    old = yaml.safe_load((folder / "agent.yml").read_text())

    views = keep_order([v["identifier"] for v in live["data_sources"].get("tables", [])], old["metric_views"])
    questions = keep_order([from_lines(q["question"]) for q in live["config"].get("sample_questions", [])],
                           old["sample_questions"])
    dump_yaml(folder / "agent.yml", {"metric_views": views, "sample_questions": questions})

    instructions = live["instructions"].get("text_instructions", [])
    (folder / "instructions.md").write_text(from_lines(instructions[0]["content"]) + "\n" if instructions else "")

    names = {read_example(p)[0]: p.name for p in (folder / "examples").glob("*.sql")}
    for p in (folder / "examples").glob("*.sql"):
        p.unlink()
    for ex in live["instructions"].get("example_question_sqls", []):
        q = from_lines(ex["question"])
        path = folder / "examples" / names.get(q, slug(q) + ".sql")
        path.write_text(f"-- question: {q}\n{from_lines(ex['sql'])}\n")

    # Benchmarks are shared, so update them in place and add new ones to the matching metric view's file.
    files = load_benchmarks()
    by_id = {uid("benchmark", q["name"]): q for b in files.values() for q in b["questions"]}
    seen = set()
    for item in live.get("benchmarks", {}).get("questions", []):
        q, sql = from_lines(item["question"]), from_lines(item["answer"][0]["content"]) + "\n"
        if item["id"] in by_id:
            by_id[item["id"]].update(question=q, sql=sql)
            seen.add(item["id"])
            continue
        view = next((v for v in views if v.replace(TOKEN, schema) in sql.replace(TOKEN, schema)), views[0])
        path = BENCHMARKS / f"{view.split('.')[-1]}.yml"
        files.setdefault(path, {"metric_view": view, "questions": []})["questions"].append(
            {"name": slug(q), "question": q, "sql": sql})
        seen.add(uid("benchmark", slug(q)))
        print(f"new benchmark '{q}' -> {path.relative_to(ROOT)}")
    for path, data in files.items():
        dump_yaml(path, data)
        for q in data["questions"]:
            if data["metric_view"] in views and uid("benchmark", q["name"]) not in seen:
                print(f"warning: benchmark '{q['name']}' is in git but not in the live agent (kept; it's shared)")

    if canon(build_spec(agent, schema)) != canon(live_raw):
        print("warning: the live agent has settings these files don't capture; review before redeploying")
    print(f"exploded {agent} into {folder.relative_to(ROOT)}")


def evaluate():
    w = WorkspaceClient()
    failed = False
    for agent, space_id in space_ids().items():
        base = f"/api/2.0/genie/spaces/{space_id}/eval-runs"
        run = w.api_client.do("POST", base, body={})
        while run.get("eval_run_status") in (None, "NOT_STARTED", "RUNNING"):
            time.sleep(10)
            run = w.api_client.do("GET", f"{base}/{run['eval_run_id']}")
        run_url = f"{base}/{run['eval_run_id']}/results"
        print(f"\n{agent}: {run.get('num_correct', 0)}/{run.get('num_questions', 0)} correct ({run['eval_run_status']})")
        for r in w.api_client.do("GET", run_url).get("eval_results", []):
            detail = w.api_client.do("GET", f"{run_url}/{r['result_id']}")
            print(f"  {detail.get('assessment', '?'):13} {r['question']}")
        failed |= run["eval_run_status"] != "DONE" or run.get("num_correct") != run.get("num_questions")
    sys.exit(1 if failed else 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build").add_argument("--schema", required=True)
    p = sub.add_parser("explode")
    p.add_argument("agent")
    p.add_argument("--schema", required=True)
    sub.add_parser("evaluate")
    args = parser.parse_args()
    if args.command == "build":
        build(args.schema)
    elif args.command == "explode":
        explode(args.agent, args.schema)
    else:
        evaluate()


if __name__ == "__main__":
    main()
