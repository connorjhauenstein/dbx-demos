"""Manage Genie agents as readable files. File keys use the Genie UI's names (see README).

  python genie_as_code.py build            files -> .build/ (specs + DAB resources)
  python genie_as_code.py test [--sql]     check the files (and run their SQL on the warehouse)
  python genie_as_code.py explode <agent>  live agent -> files
  python genie_as_code.py evaluate         run every agent's benchmarks

Every command takes --target (default: dev). The catalog, schema, and warehouse come from that
bundle target, and `{schema}` in the files stands for <catalog>.<schema>. Usually run through `make`.
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
from databricks.sdk.service.sql import StatementParameterListItem

ROOT = Path(__file__).resolve().parent
AGENTS = ROOT / "agents"
BENCHMARKS = ROOT / "benchmarks"
BUILD = ROOT / ".build"
TOKEN = "{schema}"

# File key (Genie UI name) -> API key
COLUMN_KEYS = {"description": "description", "synonyms": "synonyms", "format_assistance": "enable_format_assistance",
               "entity_matching": "enable_entity_matching", "hidden": "exclude"}
EXPRESSION_KINDS = {"filters": "filters", "measures": "measures", "fields": "expressions"}
RELATIONSHIPS = ("many_to_one", "one_to_many", "one_to_one", "many_to_many")
PARAM_TYPES = {"STRING": "STRING", "INTEGER": "INT", "DECIMAL": "DECIMAL", "DOUBLE": "DOUBLE",
               "BOOLEAN": "BOOLEAN", "DATE": "DATE", "DATETIME": "TIMESTAMP"}  # Genie type -> SQL type
# Spec keys this tool manages; anything else the API returns is kept in agent.yml `extra`.
MANAGED = {"": {"version", "config", "data_sources", "instructions", "benchmarks"},
           "config": {"sample_questions"}, "data_sources": {"tables", "metric_views"},
           "instructions": {"text_instructions", "example_question_sqls", "sql_functions", "join_specs", "sql_snippets"},
           "benchmarks": {"questions"}}


# ---------------------------------------------------------------- files

class Dumper(yaml.SafeDumper):
    """Indented lists, double quotes where YAML needs them, `|` blocks for multi-line text."""

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


def _str(dumper, s):
    style = None
    if "\n" in s:
        style = "|"
    elif s[:1] in "{`" or dumper.resolve(yaml.ScalarNode, s, (True, False)) != "tag:yaml.org,2002:str":
        style = '"'  # strings YAML would misread (dates, booleans, {schema}, backticks)
    return dumper.represent_scalar("tag:yaml.org,2002:str", s, style=style)


Dumper.add_representer(str, _str)


def read_yaml(path, default=None):
    return yaml.safe_load(path.read_text()) if path.exists() else default


def write_yaml(path, data):
    """Write data, or delete the file when there's nothing to write."""
    if data:
        path.write_text(yaml.dump(data, Dumper=Dumper, sort_keys=False, allow_unicode=True, width=1000))
    elif path.exists():
        path.unlink()


def read_query(path):
    """An example query is a SQL file with a YAML header in a leading /* */ comment."""
    text = path.read_text()
    match = re.match(r"\s*/\*(.*?)\*/\s*(.*)", text, re.S)
    if not match:
        raise ValueError(f"{path.relative_to(ROOT)}: missing the /* question: ... */ header")
    header = yaml.load(match.group(1), Loader=yaml.BaseLoader) or {}  # BaseLoader: plain strings only, no objects
    return {**header, "sql": match.group(2).strip()}


def write_query(path, query):
    header = {k: v for k, v in query.items() if k != "sql"}
    path.write_text(f"/*\n{yaml.dump(header, Dumper=Dumper, sort_keys=False, width=1000)}*/\n{query['sql']}\n")


def load_agent(agent):
    folder = AGENTS / agent
    instructions = folder / "general_instructions.md"
    return {
        "agent": read_yaml(folder / "agent.yml"),
        "general_instructions": instructions.read_text().strip() if instructions.exists() else "",
        "queries": {p.name: read_query(p) for p in sorted((folder / "queries").glob("*.sql"))},
        "joins": read_yaml(folder / "joins.yml", []),
        "sql_expressions": read_yaml(folder / "sql_expressions.yml", {}),
        "benchmarks": read_yaml(folder / "benchmarks.yml", []),
    }


def tables_of(cfg):
    return [s["table"] for s in cfg.get("sources", []) if "table" in s]


def functions_of(cfg):
    return [s["function"] for s in cfg.get("sources", []) if "function" in s]


def shared_benchmarks():
    return {p: read_yaml(p) for p in sorted(BENCHMARKS.glob("*.yml"))}


def agent_names():
    return sorted(p.name for p in AGENTS.iterdir() if (p / "agent.yml").exists())


# ---------------------------------------------------------------- build

def uid(*parts):
    return hashlib.md5(":".join(parts).encode()).hexdigest()


def lines(text):
    rows = str(text).strip().split("\n")
    return [r + "\n" for r in rows[:-1]] + rows[-1:]


def unlines(rows):
    return "".join(rows).strip()


def prune(o):
    """Drop empty lists/dicts; the API omits them."""
    if isinstance(o, dict):
        return {k: prune(v) for k, v in o.items() if prune(v) not in ([], {}, None, "")}
    if isinstance(o, list):
        return [prune(v) for v in o]
    return o


def merge(base, extra):
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            merge(base[k], v)
        else:
            base[k] = v
    return base


def table_spec(source):
    spec = {"identifier": source["table"]}
    if source.get("description"):
        spec["description"] = lines(source["description"])
    configs = []
    for name, settings in (source.get("columns") or {}).items():
        config = {"column_name": name}
        for key, value in (settings or {}).items():
            config[COLUMN_KEYS[key]] = lines(value) if key == "description" else value
        if config.get("enable_entity_matching"):
            config["enable_format_assistance"] = True  # the API turns this on with entity matching
        configs.append(config)
    if configs:
        spec["column_configs"] = configs
    return spec


def query_spec(query):
    spec = {"id": uid("example", query["question"]), "question": lines(query["question"]), "sql": lines(query["sql"])}
    params = []
    for p in query.get("parameters", []):
        param = {"name": p["keyword"], "type_hint": p["type"]}
        if p.get("comment"):
            param["description"] = lines(p["comment"])
        if "default" in p:
            values = p["default"] if isinstance(p["default"], list) else [p["default"]]
            param["default_value"] = {"values": values}
        params.append(param)
    if params:
        spec["parameters"] = params
    if query.get("usage_guidance"):
        spec["usage_guidance"] = lines(query["usage_guidance"])
    return spec


def join_spec(join):
    if join["relationship"] not in RELATIONSHIPS:
        raise ValueError(f"join relationship must be one of {', '.join(RELATIONSHIPS)}")
    left, right = join["left"], join["right"]
    spec = {"id": uid("join", left["table"], left["alias"], right["table"], right["alias"]),
            "left": {"identifier": left["table"], "alias": left["alias"]},
            "right": {"identifier": right["table"], "alias": right["alias"]},
            "sql": [join["condition"], f"--rt=FROM_RELATIONSHIP_TYPE_{join['relationship'].upper()}--"]}
    if join.get("comment"):
        spec["comment"] = lines(join["comment"])
    if join.get("instructions"):
        spec["instruction"] = lines(join["instructions"])
    return spec


def expression_spec(api_kind, item):
    spec = {"id": uid(api_kind, item["name"]), "display_name": item["name"], "sql": lines(item["code"])}
    if item.get("alias"):
        spec["alias"] = item["alias"]
    if item.get("synonyms"):
        spec["synonyms"] = item["synonyms"]
    if item.get("instructions"):
        spec["instruction"] = lines(item["instructions"])
    return spec


def benchmark_spec(b):
    spec = {"id": uid("benchmark", b["name"]), "question": lines(b["question"]),
            "answer": [{"format": "SQL", "content": lines(b["sql"])}]}
    if b.get("evaluation_note"):
        spec["evaluation_note"] = lines(b["evaluation_note"])
    return spec


def applicable_benchmarks(tables):
    return [q for data in shared_benchmarks().values() if data["source"] in tables for q in data["questions"]]


def build_spec(agent, schema):
    a = load_agent(agent)
    cfg = a["agent"]
    expressions = a["sql_expressions"]
    spec = {
        "version": 2,
        "config": {"sample_questions": [{"id": uid("sample", q), "question": lines(q)} for q in cfg.get("common_questions", [])]},
        "data_sources": {"tables": [table_spec(s) for s in cfg["sources"] if "table" in s]},
        "instructions": {
            "text_instructions": [{"id": uid("instructions"), "content": lines(a["general_instructions"])}]
            if a["general_instructions"] else [],
            "example_question_sqls": [query_spec(q) for q in a["queries"].values()],
            "sql_functions": [{"id": uid("function", f), "identifier": f} for f in functions_of(cfg)],
            "join_specs": [join_spec(j) for j in a["joins"]],
            "sql_snippets": {api: [expression_spec(api, i) for i in expressions.get(kind, [])]
                             for kind, api in EXPRESSION_KINDS.items()},
        },
        "benchmarks": {"questions": [benchmark_spec(b) for b in applicable_benchmarks(tables_of(cfg)) + a["benchmarks"]]},
    }
    spec = prune(merge(spec, cfg.get("extra")))
    spec = json.loads(json.dumps(spec).replace(TOKEN, schema))
    sort_spec(spec)
    return spec


def sort_spec(spec):
    """The API rejects collections that aren't sorted."""
    for t in spec.get("data_sources", {}).get("tables", []):
        t.get("column_configs", []).sort(key=lambda c: c["column_name"])
    spec.get("data_sources", {}).get("tables", []).sort(key=lambda t: t["identifier"])
    ins = spec.get("instructions", {})
    groups = [spec.get("config", {}).get("sample_questions", []), spec.get("benchmarks", {}).get("questions", []),
              ins.get("text_instructions", []), ins.get("example_question_sqls", []), ins.get("join_specs", [])]
    groups += list(ins.get("sql_snippets", {}).values())
    for items in groups:
        items.sort(key=lambda i: i["id"])
    ins.get("sql_functions", []).sort(key=lambda f: (f["id"], f["identifier"]))


def resource(agent):
    cfg = load_agent(agent)["agent"]
    res = {"title": cfg["title"], "description": cfg.get("description", ""),
           "warehouse_id": cfg.get("warehouse_id", "${var.warehouse_id}"), "file_path": f"{agent}.geniespace.json"}
    if cfg.get("permissions"):
        res["permissions"] = cfg["permissions"]
    return res


def build(target):
    schema = bundle_settings(target)["schema"]
    BUILD.mkdir(exist_ok=True)
    for old in BUILD.glob("*.geniespace.json"):
        old.unlink()
    agents = agent_names()
    for agent in agents:
        (BUILD / f"{agent}.geniespace.json").write_text(json.dumps(build_spec(agent, schema), indent=2) + "\n")
        print(f"built .build/{agent}.geniespace.json")
    resources = {"resources": {"genie_spaces": {a: resource(a) for a in agents}}}
    (BUILD / "genie_agents.yml").write_text(yaml.dump(resources, Dumper=Dumper, sort_keys=False))
    print("built .build/genie_agents.yml")


# ---------------------------------------------------------------- test

def sql_texts(spec):
    """Every SQL string in a spec, with a label."""
    ins = spec.get("instructions", {})
    for e in ins.get("example_question_sqls", []):
        yield f"query '{unlines(e['question'])}'", unlines(e["sql"])
    for b in spec.get("benchmarks", {}).get("questions", []):
        yield f"benchmark '{unlines(b['question'])}'", unlines(b["answer"][0]["content"])
    for j in ins.get("join_specs", []):
        yield f"join {j['left']['alias']}->{j['right']['alias']}", j["sql"][0]
    for kind, items in ins.get("sql_snippets", {}).items():
        for i in items:
            yield f"{kind} '{i.get('display_name')}'", unlines(i["sql"])


def check_spec(agent, spec, schema):
    problems = []
    ins = spec.get("instructions", {})
    tables = {t["identifier"] for t in spec["data_sources"].get("tables", [])}
    functions = {f["identifier"] for f in ins.get("sql_functions", [])}
    for label, sql in sql_texts(spec):
        for ref in re.findall(re.escape(schema) + r"\.\w+(?!\w|\s*\()", sql):  # tables, not function calls
            if ref not in tables | functions:
                problems.append(f"{agent}: {label} uses {ref}, which isn't in sources")
    for j in ins.get("join_specs", []):
        for side in ("left", "right"):
            if j[side]["identifier"] not in tables:
                problems.append(f"{agent}: join uses {j[side]['identifier']}, which isn't in sources")
    for e in ins.get("example_question_sqls", []):
        for p in e.get("parameters", []):
            if p["type_hint"] not in PARAM_TYPES:
                problems.append(f"{agent}: parameter {p['name']} type must be one of {', '.join(PARAM_TYPES)}")
            if f":{p['name']}" not in unlines(e["sql"]):
                problems.append(f"{agent}: parameter {p['name']} isn't used as :{p['name']} in its SQL")
    # IDs come from names/questions, so a duplicate ID means the same item is defined twice.
    questions = spec.get("config", {}).get("sample_questions", []) + spec.get("benchmarks", {}).get("questions", [])
    others = [i for key in ("example_question_sqls", "join_specs") for i in ins.get(key, [])]
    others += [i for items in ins.get("sql_snippets", {}).values() for i in items]
    for items in (questions, others):
        seen = set()
        for i in items:
            if i["id"] in seen:
                label = unlines(i["question"]) if "question" in i else i.get("display_name") or i["sql"][0]
                problems.append(f"{agent}: '{label}' is defined twice (same name or question)")
            seen.add(i["id"])
    return problems


def run_sql(w, warehouse, sql, params=()):
    r = w.statement_execution.execute_statement(statement=sql, warehouse_id=warehouse, wait_timeout="50s",
                                                row_limit=1000, parameters=list(params) or None)
    if r.status.state.value != "SUCCEEDED":
        return None, r.status.error.message if r.status.error else r.status.state.value
    return (r.result.data_array or []) if r.result else [], None


def check_function(agent, name, w, warehouse):
    """Genie only accepts table functions here. A scalar function silently stops the agent answering,
    and DATE arguments are rejected (tested 2026-11)."""
    rows, error = run_sql(w, warehouse, f"DESCRIBE FUNCTION EXTENDED {name}")
    if error:
        return [f"{agent}: function {name} failed: {error.splitlines()[0][:200]}"]
    info, field = {}, None
    for (line,) in rows:
        if re.match(r"\w[\w ]*:", line):
            field, line = line.split(":", 1)
        info.setdefault(field, []).append(line.strip())
    problems = []
    if info.get("Type") != ["TABLE"]:
        problems.append(f"{agent}: SQL function {name} must be a table function (RETURNS TABLE)")
    for arg in info.get("Input", []):
        if arg.split()[-1:] == ["DATE"]:
            problems.append(f"{agent}: function {name} argument '{arg.split()[0]}' is DATE, which Genie rejects; use STRING")
    return problems


def check_sql(agent, spec, w, warehouse, done):
    """Run each source, column, function, query, benchmark and join against the warehouse."""
    problems, ins = [], spec.get("instructions", {})
    for t in spec["data_sources"].get("tables", []):
        rows, error = run_sql(w, warehouse, f"DESCRIBE TABLE {t['identifier']}")  # works for metric views too
        if error:
            problems.append(f"{agent}: source {t['identifier']} failed: {error.splitlines()[0][:200]}")
            continue
        columns = {r[0] for r in rows}
        for c in t.get("column_configs", []):
            if c["column_name"] not in columns:
                problems.append(f"{agent}: {t['identifier']} has no column {c['column_name']}")
    for f in ins.get("sql_functions", []):
        problems += check_function(agent, f["identifier"], w, warehouse)
    checks = []
    for e in ins.get("example_question_sqls", []):
        params = [StatementParameterListItem(name=p["name"], value=p["default_value"]["values"][0],
                                             type=PARAM_TYPES.get(p["type_hint"], "STRING"))
                  for p in e.get("parameters", []) if p.get("default_value")]
        checks.append((f"query '{unlines(e['question'])}'", unlines(e["sql"]), params, False))
    for b in spec.get("benchmarks", {}).get("questions", []):
        checks.append((f"benchmark '{unlines(b['question'])}'", unlines(b["answer"][0]["content"]), [], True))
    for j in ins.get("join_specs", []):
        sql = (f"SELECT 1 FROM {j['left']['identifier']} AS `{j['left']['alias']}` "
               f"JOIN {j['right']['identifier']} AS `{j['right']['alias']}` ON {j['sql'][0]} LIMIT 1")
        checks.append((f"join {j['left']['alias']}->{j['right']['alias']}", sql, [], False))
    for label, sql, params, want_rows in checks:
        if sql in done:
            continue
        done.add(sql)
        rows, error = run_sql(w, warehouse, sql, params)
        if error:
            problems.append(f"{agent}: {label} failed: {error.splitlines()[0][:200]}")
        elif want_rows and not rows:
            print(f"  note: {agent}: {label} returns no rows")
    return problems


def test(target, with_sql):
    # Offline checks don't need a workspace, so they use a placeholder schema.
    settings = bundle_settings(target) if with_sql else {"schema": "catalog.schema"}
    schema = settings["schema"]
    problems, specs = [], {}
    for agent in agent_names():
        try:
            specs[agent] = build_spec(agent, schema)
        except Exception as e:  # report every broken agent, not just the first
            problems.append(f"{agent}: can't build: {e!r}")
            continue
        problems += check_spec(agent, specs[agent], schema)
    used = {t for a in agent_names() for t in tables_of(load_agent(a)["agent"])}
    for path, data in shared_benchmarks().items():
        if data["source"] not in used:
            problems.append(f"{path.relative_to(ROOT)}: no agent uses {data['source']}")
    if with_sql:
        w, warehouse, done = WorkspaceClient(), settings["warehouse_id"], set()
        for agent, spec in specs.items():
            problems += check_sql(agent, spec, w, warehouse, done)
    for p in problems:
        print(f"FAIL {p}")
    print(f"{len(specs)} agents checked{' (with SQL)' if with_sql else ''}: {len(problems)} problems")
    sys.exit(1 if problems else 0)


# ---------------------------------------------------------------- explode

def bundle(target, command):
    result = subprocess.run(["databricks", "bundle", command, "--target", target, "-o", "json"], cwd=ROOT,
                            capture_output=True, text=True)
    if result.returncode:
        sys.exit(f"databricks bundle {command} failed:\n{result.stderr.strip()}")
    return json.loads(result.stdout)


def bundle_settings(target):
    """Catalog, schema, and warehouse for a bundle target, from databricks.yml."""
    v = {k: x.get("value") for k, x in bundle(target, "validate")["variables"].items()}
    return {"schema": f"{v['catalog']}.{v['schema']}", "warehouse_id": v["warehouse_id"]}


def space_ids(target):
    return {k: v["id"] for k, v in bundle(target, "summary")["resources"].get("genie_spaces", {}).items()}


def fetch(w, space_id):
    space = w.api_client.do("GET", f"/api/2.0/genie/spaces/{space_id}", query={"include_serialized_space": "true"})
    return json.loads(space["serialized_space"])


def ordered(new, old_keys, key=lambda x: x):
    """Items already in the files keep their order (old_keys); new items go last."""
    rank = {k: i for i, k in enumerate(old_keys)}
    return sorted(new, key=lambda x: rank.get(key(x), len(rank)))


def text(rows):
    return unlines(rows) if rows else None


def compact(d):
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}


def unmanaged(live):
    """Spec keys this tool doesn't model, so they survive the round trip in agent.yml `extra`."""
    extra = {k: v for k, v in live.items() if k not in MANAGED[""]}
    for section in ("config", "data_sources", "instructions", "benchmarks"):
        rest = {k: v for k, v in live.get(section, {}).items() if k not in MANAGED[section]}
        if rest:
            extra[section] = rest
    snippets = {k: v for k, v in live.get("instructions", {}).get("sql_snippets", {}).items()
                if k not in EXPRESSION_KINDS.values()}
    if snippets:
        extra.setdefault("instructions", {})["sql_snippets"] = snippets
    return extra


def source_key(s):
    return ("table", s["table"]) if "table" in s else ("function", s["function"])


def explode(target, agent):
    schema = bundle_settings(target)["schema"]
    ids = space_ids(target)
    if agent not in ids:
        sys.exit(f"no deployed agent '{agent}' in target '{target}'; deployed: {', '.join(ids) or 'none'}")
    live_raw = fetch(WorkspaceClient(), ids[agent])
    live = json.loads(json.dumps(live_raw).replace(schema, TOKEN))
    folder = AGENTS / agent
    old = load_agent(agent)
    old_cfg = old["agent"]
    ins = live.get("instructions", {})

    # agent.yml: title/description/warehouse/permissions stay as written; the rest comes from the live agent.
    old_columns = {s["table"]: list(s.get("columns") or {}) for s in old_cfg.get("sources", []) if "table" in s}
    sources = []
    for t in live["data_sources"].get("tables", []) + live["data_sources"].get("metric_views", []):
        columns = {}
        for c in ordered(t.get("column_configs", []), old_columns.get(t["identifier"], []), lambda c: c["column_name"]):
            settings = compact({k: (text(c[api]) if k == "description" else c[api])
                                for k, api in COLUMN_KEYS.items() if api in c})
            if settings.get("entity_matching"):
                settings.pop("format_assistance", None)  # implied by entity matching
            columns[c["column_name"]] = settings or None
        sources.append(compact({"table": t["identifier"], "description": text(t.get("description")), "columns": columns}))
    sources += [{"function": f["identifier"]} for f in ins.get("sql_functions", [])]
    cfg = {k: v for k, v in old_cfg.items() if k in ("title", "description", "warehouse_id", "permissions")}
    cfg["common_questions"] = ordered([text(q["question"]) for q in live.get("config", {}).get("sample_questions", [])],
                                      old_cfg.get("common_questions", []))
    cfg["sources"] = ordered(sources, [source_key(s) for s in old_cfg.get("sources", [])], source_key)
    cfg["extra"] = unmanaged(live)
    write_yaml(folder / "agent.yml", compact(cfg))

    instructions = ins.get("text_instructions", [])
    (folder / "general_instructions.md").write_text(text(instructions[0]["content"]) + "\n" if instructions else "")

    files = {q["question"]: name for name, q in old["queries"].items()}
    (folder / "queries").mkdir(exist_ok=True)
    for p in (folder / "queries").glob("*.sql"):
        p.unlink()
    for e in ins.get("example_question_sqls", []):
        query = compact({
            "question": text(e["question"]), "usage_guidance": text(e.get("usage_guidance")),
            "parameters": [compact({"keyword": p["name"], "type": p["type_hint"],
                                    "default": (lambda v: v[0] if len(v) == 1 else v)(p["default_value"]["values"])
                                    if p.get("default_value") else None,
                                    "comment": text(p.get("description"))}) for p in e.get("parameters", [])],
        })
        query["sql"] = text(e["sql"])
        write_query(folder / "queries" / files.get(query["question"], slug(query["question"]) + ".sql"), query)

    joins = [compact({"left": {"table": j["left"]["identifier"], "alias": j["left"]["alias"]},
                      "right": {"table": j["right"]["identifier"], "alias": j["right"]["alias"]},
                      "condition": j["sql"][0],
                      "relationship": re.search(r"--rt=FROM_RELATIONSHIP_TYPE_(\w+)--", j["sql"][1]).group(1).lower(),
                      "instructions": text(j.get("instruction")), "comment": text(j.get("comment"))})
             for j in ins.get("join_specs", [])]
    join_key = lambda j: (j["left"]["table"], j["left"]["alias"], j["right"]["table"], j["right"]["alias"])
    write_yaml(folder / "joins.yml", ordered(joins, [join_key(j) for j in old["joins"]], join_key))

    expressions = {}
    for kind, api in EXPRESSION_KINDS.items():
        items = [compact({"name": i.get("display_name") or i.get("alias"), "code": text(i["sql"]),
                          "synonyms": i.get("synonyms"), "instructions": text(i.get("instruction")),
                          "alias": i.get("alias")})
                 for i in ins.get("sql_snippets", {}).get(api, [])]
        old_names = [i["name"] for i in old["sql_expressions"].get(kind, [])]
        expressions[kind] = ordered(items, old_names, lambda i: i["name"])
    write_yaml(folder / "sql_expressions.yml", compact(expressions))

    explode_benchmarks(agent, live, tables_of(cfg), old)

    rebuilt = build_spec(agent, schema)
    for section in sorted(set(rebuilt) | set(live_raw)):
        if canon(rebuilt.get(section)) != canon(live_raw.get(section)):
            print(f"warning: '{section}' in the live agent doesn't round-trip exactly; check git diff before redeploying")
    print(f"exploded {agent} into {folder.relative_to(ROOT)}")


def explode_benchmarks(agent, live, tables, old):
    """Shared benchmarks are updated in place; new ones go to the agent's own benchmarks.yml."""
    shared = shared_benchmarks()
    by_id = {uid("benchmark", q["name"]): q for data in shared.values() for q in data["questions"]}
    local_ids = {uid("benchmark", q["name"]): q for q in old["benchmarks"]}
    local, seen = [], set()
    for item in live.get("benchmarks", {}).get("questions", []):
        q = compact({"question": text(item["question"]), "evaluation_note": text(item.get("evaluation_note")),
                     "sql": text(item["answer"][0]["content"]) + "\n"})
        seen.add(item["id"])
        if item["id"] in by_id:
            by_id[item["id"]].pop("evaluation_note", None)
            by_id[item["id"]].update(q)
        elif item["id"] in local_ids:
            local.append(compact({**local_ids[item["id"]], "evaluation_note": None, **q}))
        else:
            local.append({"name": slug(q["question"]), **q})
            print(f"new benchmark '{q['question']}' -> agents/{agent}/benchmarks.yml")
    for path, data in shared.items():
        write_yaml(path, data)
        for q in data["questions"]:
            if data["source"] in tables and uid("benchmark", q["name"]) not in seen:
                print(f"warning: shared benchmark '{q['name']}' isn't in the live agent (kept in {path.name})")
    write_yaml(AGENTS / agent / "benchmarks.yml", ordered(local, [q["name"] for q in old["benchmarks"]], lambda q: q["name"]))


def slug(value):
    return re.sub(r"[^a-z0-9]+", "_", value.lower())[:60].strip("_")


def canon(o):
    """Compare specs ignoring ids and list order."""
    if isinstance(o, dict):
        return {k: canon(v) for k, v in o.items() if k != "id"}
    if isinstance(o, list):
        items = [canon(v) for v in o]
        return sorted(items, key=json.dumps) if all(isinstance(i, dict) for i in items) else items
    return o


# ---------------------------------------------------------------- evaluate

def evaluate(target):
    w = WorkspaceClient()
    failed = False
    for agent, space_id in space_ids(target).items():
        base = f"/api/2.0/genie/spaces/{space_id}/eval-runs"
        run = w.api_client.do("POST", base, body={})
        while run.get("eval_run_status") in (None, "NOT_STARTED", "RUNNING"):
            time.sleep(10)
            run = w.api_client.do("GET", f"{base}/{run['eval_run_id']}")
        results = f"{base}/{run['eval_run_id']}/results"
        print(f"\n{agent}: {run.get('num_correct', 0)}/{run.get('num_questions', 0)} correct ({run['eval_run_status']})")
        for r in w.api_client.do("GET", results).get("eval_results", []):
            detail = w.api_client.do("GET", f"{results}/{r['result_id']}")
            print(f"  {detail.get('assessment', '?'):13} {r['question']}")
        failed |= run["eval_run_status"] != "DONE" or run.get("num_correct") != run.get("num_questions")
    sys.exit(1 if failed else 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--target", default="dev", help="bundle target (default: dev)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build", parents=[common])
    sub.add_parser("test", parents=[common]).add_argument(
        "--sql", action="store_true", help="also run every query against the target's warehouse")
    sub.add_parser("explode", parents=[common]).add_argument("agent")
    sub.add_parser("evaluate", parents=[common])
    args = parser.parse_args()
    if args.command == "build":
        build(args.target)
    elif args.command == "test":
        test(args.target, args.sql)
    elif args.command == "explode":
        explode(args.target, args.agent)
    else:
        evaluate(args.target)


if __name__ == "__main__":
    main()
