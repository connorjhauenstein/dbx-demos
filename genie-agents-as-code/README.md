# Genie agents as code

Manage every setting of a Genie agent as small, readable files in git instead of one large
`serialized_space` JSON. Benchmarks can be shared across every agent that uses the same table
or metric view.

```
genie-agent-template/      # copy to agents/<name>/ to add an agent; shows every setting
agents/
  growth/  monetization/   # simple agents over metric views
  user_activity/           # uses every setting (columns, joins, SQL expressions, functions, parameters, ...)
benchmarks/                # shared: each file's questions go to EVERY agent using its `source`
genie_as_code.py           # build | test | explode | evaluate
databricks.yml             # bundle; includes the generated .build/genie_agents.yml
```

`{schema}` in the files stands for `<catalog>.<schema>`, so the same files deploy anywhere.

## Files, Genie UI, and API names

File keys use the Genie UI's names. The API (`serialized_space`) sometimes calls things differently;
`build` and `explode` translate.

| Genie UI (Configure / Benchmark) | Our file and key | API (`serialized_space`) |
|---|---|---|
| **About** → Name | `agent.yml` → `title` | space `title` (not in the spec) |
| About → Description | `agent.yml` → `description` | space `description` |
| About → Warehouse | `agent.yml` → `warehouse_id` | space `warehouse_id` |
| Share | `agent.yml` → `permissions` | DAB `permissions` |
| About → Common questions | `agent.yml` → `common_questions` | `config.sample_questions` |
| **Sources** → Tables, Metric Views | `agent.yml` → `sources: - table:` | `data_sources.tables` (metric views included) |
| Sources → SQL functions | `agent.yml` → `sources: - function:` | `instructions.sql_functions` |
| Source → Description | `table` → `description` | `tables[].description` |
| Column → Description / Synonyms | `columns.<col>.description` / `synonyms` | `column_configs[].description` / `synonyms` |
| Column → Format assistance | `columns.<col>.format_assistance` | `enable_format_assistance` |
| Column → Entity matching | `columns.<col>.entity_matching` | `enable_entity_matching` |
| Column → Hide column | `columns.<col>.hidden` | `exclude` |
| **Instructions** → General Instructions | `general_instructions.md` | `instructions.text_instructions` (max 1) |
| **Examples** → Queries: title, SQL | `queries/*.sql`: `question`, the SQL body | `example_question_sqls[]`: `question`, `sql` |
| Query → Usage Guidance | `usage_guidance` | `usage_guidance` |
| Query → Parameters: Keyword / Data type / Comment | `parameters`: `keyword` / `type` / `comment` (+ `default`) | `parameters[]`: `name` / `type_hint` / `description` (+ `default_value`) |
| Examples → Filters / Measures / **Fields** | `sql_expressions.yml` → `filters` / `measures` / `fields` | `sql_snippets.filters` / `measures` / **`expressions`** |
| Expression → Name / Code / Synonyms / Instructions | `name` / `code` / `synonyms` / `instructions` | `display_name` / `sql` / `synonyms` / `instruction` |
| (not shown) | expression `alias` (optional) | `alias` |
| Examples → **Joins**: Left Table / Right Table | `joins.yml` → `left.table` / `right.table` | `join_specs[].left.identifier` / `right.identifier` |
| Join → Join condition | `condition` | `sql[0]` |
| Join → Relationship Type | `relationship: many_to_one` | `sql[1]`: `--rt=FROM_RELATIONSHIP_TYPE_MANY_TO_ONE--` |
| Join → Instructions | `instructions` | `instruction` |
| (not shown) | join `alias`, `comment` | `left.alias`, `right.alias`, `comment` |
| **Benchmark** → Question | `benchmarks.yml` (or shared `benchmarks/`) → `question` | `benchmarks.questions[].question` |
| Benchmark → Evaluation note (Agent mode only) | `evaluation_note` | `evaluation_note` |
| Benchmark → Ground truth SQL answer | `sql` | `answer[0].content` (`format: SQL`) |
| (not shown) | benchmark `name` (stable ID) | `id` |

Parameter data types in the UI: String, Date, Date and Time, Decimal, Integer. In files use the API
values `STRING`, `DATE`, `DATETIME`, `DECIMAL`, `INTEGER` (the API also accepts `DOUBLE` and `BOOLEAN`).

Spec fields this tool doesn't model yet are kept by `explode` in `agent.yml` under `extra:` and merged
back by `build`, so nothing is lost.

## Commands

| Command | Does |
|---|---|
| `build --schema S` | Writes `.build/<agent>.geniespace.json` and the DAB resources (`.build/genie_agents.yml`). Generates stable IDs, sorts collections the way the API requires, and adds shared benchmarks. |
| `test --schema S` | Offline: every agent builds; SQL only references the agent's sources; joins, parameter types, and relationships are valid; IDs are unique; every shared benchmark is used. |
| `test --schema S --sql` | Also runs every query, benchmark, and join on the warehouse, checks configured columns exist, and checks SQL functions are ones Genie accepts. |
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
- SQL functions must be **table functions** (`RETURNS TABLE`). A scalar function makes the agent
  stop answering without an error, and `DATE` arguments are rejected. Scalar functions are fine to
  call inside example queries.
- Parameter types: `STRING`, `INTEGER`, `DECIMAL`, `DOUBLE`, `BOOLEAN`, `DATE`, `DATETIME`; the API checks each default against its type.
- Entity matching turns on format assistance for the same column.
- One General Instructions entry per agent; one ground truth SQL answer per benchmark.
