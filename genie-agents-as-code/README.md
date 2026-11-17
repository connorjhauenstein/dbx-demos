# Genie agents as code

Manage every setting of a Genie agent as small, readable files in git instead of one large
`serialized_space` JSON. Benchmarks can be shared across every agent that uses the same table
or metric view.

```
genie-agent-template/      # copy to agents/<name>/ to add an agent; shows every setting
agents/
  growth/  monetization/   # simple agents over metric views
  user_activity/           # uses every setting (columns, joins, snippets, functions, parameters, ...)
benchmarks/                # shared: each file's questions go to EVERY agent using its data_source
genie_as_code.py           # build | test | explode | evaluate
databricks.yml             # bundle; includes the generated .build/genie_agents.yml
```

`{schema}` in the files stands for `<catalog>.<schema>`, so the same files deploy anywhere.

## What each file holds

| File | Genie setting |
|---|---|
| `agent.yml` | title, description, warehouse, permissions, data sources (with table descriptions and per-column description / synonyms / exclude / entity matching / format assistance), sample questions, SQL functions |
| `instructions.md` | the text instruction (Genie allows one) |
| `examples/*.sql` | example SQL; a `/* */` YAML header holds the question, usage guidance, and parameters |
| `joins.yml` | join specs: `left`, `right`, `sql`, `relationship`, `comment`, `instruction` |
| `snippets.yml` | SQL snippets: filters, expressions, measures |
| `benchmarks.yml` | benchmarks for this agent only |
| `../../benchmarks/*.yml` | shared benchmarks, keyed by `data_source` |

`genie-agent-template/` documents every key. Spec fields this tool doesn't model yet are kept by
`explode` in `agent.yml` under `extra:` and merged back by `build`, so nothing is lost.

## Commands

| Command | Does |
|---|---|
| `build --schema S` | Writes `.build/<agent>.geniespace.json` and the DAB resources (`.build/genie_agents.yml`). Generates stable IDs, sorts collections the way the API requires, and adds shared benchmarks. |
| `test --schema S` | Offline: every agent builds; SQL only references the agent's data sources; joins, parameter types, and relationships are valid; IDs are unique; every shared benchmark is used. |
| `test --schema S --sql` | Also runs every example, benchmark, and join on the warehouse, checks configured columns exist, and checks SQL functions are ones Genie accepts. |
| `explode <agent> --schema S` | Pulls a live agent back into the files, so UI edits become a small `git diff`. New UI benchmarks go to the agent's `benchmarks.yml`. |
| `evaluate` | Runs every agent's benchmarks with the Genie eval-runs API (Beta) and exits non-zero unless all are correct. |

## Deploy

```bash
pip install databricks-sdk pyyaml               # Databricks CLI >= 1.17
export DATABRICKS_CONFIG_PROFILE=<profile>
export BUNDLE_VAR_catalog=<catalog>             # schema defaults to genie_as_code
SCHEMA=$BUNDLE_VAR_catalog.genie_as_code

databricks bundle deploy                        # setup job (agents come after build)
databricks bundle run setup_demo_data           # demo tables, metric views, and functions
python genie_as_code.py build --schema $SCHEMA
python genie_as_code.py test --schema $SCHEMA --sql
databricks bundle deploy                        # creates or updates the agents
python genie_as_code.py evaluate
```

## Workflow

1. **Add an agent:** `cp -r genie-agent-template agents/<name>`, edit, then `test`.
2. **Change an agent:** edit the files, run `test --sql`, open a PR. In CI: `build`, `test --sql`,
   `databricks bundle deploy -t <staging>`, `evaluate`. On merge: deploy to prod.
3. **Someone edited in the UI:** `explode <agent>`, review `git diff`, open a PR. The next deploy
   makes the live agent match git either way.
4. **Develop without touching shared agents:** `databricks bundle deploy -t dev` creates your own
   `[dev <you>]` copies to try things in the UI and `explode` back.

To stop UI edits on shared agents, deploy prod as a service principal and give people `CAN_RUN`
in `permissions` (workspace admins can still edit, so keep `explode` as a drift check).

## Things Genie enforces (learned by testing)

- Metric views are stored under `data_sources.tables`; they must exist before an agent using them is created.
- `sql_functions` must be **table functions** (`RETURNS TABLE`). A scalar function makes the agent
  stop answering without an error, and `DATE` arguments are rejected. Scalar functions are fine to
  call inside example SQL.
- Parameter types: `STRING`, `INTEGER`, `DECIMAL`, `DOUBLE`, `BOOLEAN`, `DATE`, `DATETIME`; the API checks each default against its type.
- Entity matching turns on format assistance for the same column.
- One text instruction per agent; one SQL answer per benchmark.
