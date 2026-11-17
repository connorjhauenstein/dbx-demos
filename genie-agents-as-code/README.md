# Genie agents as code

Keep your Genie agents in git as small, readable files, and deploy them with a Databricks Asset Bundle.

Genie stores each agent as one large JSON blob. That works in the UI, but it's hard to review, reuse,
or test. This project splits every agent setting into plain files (YAML, Markdown, SQL), so you can:

- **Review changes** in a pull request like any other code.
- **Share benchmarks:** write a benchmark question once for a table or metric view, and every agent
  that uses it gets the question.
- **Test before you deploy:** catch broken SQL, missing tables, and invalid settings locally.
- **Edit in the UI if you want:** pull the changes back into files and see them as a small diff.

## How it works

```
agents/<name>/  ──build──▶  Genie spec JSON  ──bundle deploy──▶  Genie agent
      ▲                                                               │
      └────────────────────────────explode───────────────────────────┘
```

One script, `genie_as_code.py`, does four things:

| Command | What it does |
|---|---|
| `build` | Turns the files into what Genie expects, plus the bundle resources. |
| `test` | Checks the files. Add `--sql` to also run every query against your warehouse. |
| `explode <agent>` | Pulls a live agent back into the files (for edits made in the UI). |
| `evaluate` | Runs every agent's benchmarks in Genie and fails if any answer is wrong. |

## Try it

Needs the Databricks CLI (1.17 or later) and `pip install databricks-sdk pyyaml`.

```bash
export DATABRICKS_CONFIG_PROFILE=<your profile>
export BUNDLE_VAR_catalog=<a catalog you can write to>
SCHEMA=$BUNDLE_VAR_catalog.genie_as_code

databricks bundle deploy                         # creates the demo-data job
databricks bundle run setup_demo_data            # demo tables, metric views, and a function
python genie_as_code.py build --schema $SCHEMA
python genie_as_code.py test  --schema $SCHEMA --sql
databricks bundle deploy                         # creates the three demo agents
python genie_as_code.py evaluate
```

`{schema}` in the files is replaced with `<catalog>.<schema>` at build time, so the same files work in any workspace.

## Day to day

- **New agent:** copy `genie-agent-template/` to `agents/<name>/`, fill it in, run `test`.
  The template lists every setting with a comment.
- **Change an agent:** edit its files, run `test --sql`, open a pull request. After merge: `build`, deploy, `evaluate`.
- **Someone changed it in the UI:** run `explode <agent>`, review `git diff`, commit. The next deploy
  always makes the live agent match git.
- **Lock it down:** deploy as a service principal and give people `CAN_RUN` in `permissions`, so only code can change shared agents.

## What's in an agent folder

The file and key names match what you see in the Genie UI.

| File | Genie UI |
|---|---|
| `agent.yml` | **About** (name, description, warehouse, common questions), **Share** (permissions), and **Sources** (tables, metric views, SQL functions, column settings) |
| `general_instructions.md` | **Instructions** → General Instructions |
| `queries/*.sql` | **Examples** → Queries (question, SQL, parameters, usage guidance) |
| `sql_expressions.yml` | **Examples** → Filters, Measures, Fields |
| `joins.yml` | **Examples** → Joins |
| `benchmarks.yml` | **Benchmark** → Questions for this agent only |

Shared benchmarks live in `benchmarks/`. Each file names a `source`, and its questions go to every
agent that uses that source.

The demo has three agents: `growth` and `monetization` (simple, on metric views) and `user_activity`,
which uses every setting.

<details>
<summary>Exact UI ↔ file ↔ API names</summary>

| Genie UI | Our file key | API (`serialized_space`) |
|---|---|---|
| About → Common questions | `common_questions` | `config.sample_questions` |
| Sources → Tables, Metric Views | `sources: - table:` | `data_sources.tables` |
| Sources → SQL functions | `sources: - function:` | `instructions.sql_functions` |
| Column → Description, Synonyms | `description`, `synonyms` | same |
| Column → Format assistance, Entity matching | `format_assistance`, `entity_matching` | `enable_format_assistance`, `enable_entity_matching` |
| Column → Hide column | `hidden` | `exclude` |
| General Instructions | `general_instructions.md` | `text_instructions` |
| Query → title, Usage Guidance | `question`, `usage_guidance` | `question`, `usage_guidance` |
| Query → Parameter: Keyword, Data type, Comment | `keyword`, `type`, `comment`, `default` | `name`, `type_hint`, `description`, `default_value` |
| Filters / Measures / Fields | `filters` / `measures` / `fields` | `sql_snippets.filters` / `measures` / `expressions` |
| Expression → Name, Code, Synonyms, Instructions | `name`, `code`, `synonyms`, `instructions` | `display_name`, `sql`, `synonyms`, `instruction` |
| Join → Left/Right Table, Join condition | `left.table`, `right.table`, `condition` | `left/right.identifier`, `sql[0]` |
| Join → Relationship Type, Instructions | `relationship`, `instructions` | `sql[1]` (`--rt=…--`), `instruction` |
| Benchmark → Question, Evaluation note, Ground truth SQL | `question`, `evaluation_note`, `sql` | `question`, `evaluation_note`, `answer[0].content` |
| (not in UI) | table `alias`, join `comment`, expression `alias`, benchmark `name` | `alias`, `comment`, `alias`, `id` |

Anything new that Genie adds is kept as-is under `extra:` in `agent.yml`, so nothing gets lost.
</details>

## Good to know

- **SQL functions must return a table** (`RETURNS TABLE`) and can't take `DATE` arguments. A regular
  scalar function makes the agent silently stop answering. `test --sql` checks this.
  Scalar functions are fine to use inside example queries.
- **Metric views and tables must exist** before you deploy an agent that uses them.
- **Parameter types:** `STRING`, `INTEGER`, `DECIMAL`, `DATE`, `DATETIME` (shown in the UI), plus `DOUBLE` and `BOOLEAN`.
- The benchmark API that `evaluate` uses is in Beta.
