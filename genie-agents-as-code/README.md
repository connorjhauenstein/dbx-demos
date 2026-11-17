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

Everything runs through `make` (run `make` on its own to see this list):

| Command | What it does |
|---|---|
| `make test` | Checks the files offline. No workspace needed. |
| `make test-sql` | Also runs every query, join, and benchmark against your warehouse. |
| `make deploy` | Tests, builds, and deploys the agents. Stops if a test fails or if someone edited an agent in the UI since the last deploy. |
| `make eval` | Runs every agent's benchmarks in Genie and fails if any answer is wrong. |
| `make explode AGENT=<name>` | Pulls UI edits on a live agent back into the files, as one git commit. |
| `make status` | Shows which commit each agent was deployed from, and any UI edits not pulled yet. |
| `make rollback REF=<commit>` | Deploys an earlier commit without touching your checkout. |
| `make ci` | Tests, deploys, and runs benchmarks: what a pull request should pass. |

Add `TARGET=prod` to any command to use another bundle target. The catalog, schema, and warehouse
come from that target in `databricks.yml`. The work is done by one script, `genie_as_code.py`.

## Try it

Needs the Databricks CLI (1.17 or later), Python 3.9+, and `make`.

```bash
export DATABRICKS_CONFIG_PROFILE=<your profile>
export BUNDLE_VAR_catalog=<a catalog you can write to>

make install   # Python dependencies
make setup     # demo tables, metric views, and functions (from demo/)
make ci        # test, deploy the three demo agents, and run their benchmarks
```

`{schema}` in the files is replaced with the target's `<catalog>.<schema>` at build time, so the same
files work in any workspace.

## Day to day

**Working on a change (all inside one pull request):**

1. Make a branch and run `make deploy`. You get your own copies of the agents (`[dev <you>] …`).
2. Try things in the Genie UI on your copies.
3. Run `make explode AGENT=<name>`. Your UI edits land in the files as their own commit
   (`genie(<name>): pull UI changes from dev`). Look at it with `git show`; undo it with `git revert`.
4. Repeat as needed, then push. The pull request runs `make ci TARGET=staging`.
5. After merge, CI runs `make deploy eval TARGET=prod`.

**New agent:** copy `genie-agent-template/` to `agents/<name>/`, fill it in, and run `make test`. The
template lists every setting with a comment.

**Rolling back:** the normal way is `git revert <commit>` and a pull request. In an emergency,
`make rollback REF=<commit> TARGET=prod` deploys that commit straight away; revert in git afterwards
so the main branch matches what's live.

**Built-in safety checks:**

- `explode` stops if that agent's files have uncommitted changes, so every pull is its own commit.
- `explode` stops if the agent changed in both places since the last deploy (in the UI, and in files
  you pulled from teammates), because either way you'd lose one side. Deploy first, or use `FORCE=1`.
- `deploy` stops if an agent was edited in the UI and the edits aren't in your files yet. It saves the
  live version to `.build/backups/` first, so nothing is lost. Pull with `explode`, or use `FORCE=1`.
- Shared targets (anything not in development mode, like staging or prod) only deploy committed code,
  so every deploy can be rolled back.
- Deploy with `make deploy`, not `databricks bundle deploy`: the agents' bundle resources come from
  the build step, and the safety checks run there.

To stop UI edits on shared agents entirely, deploy them as a service principal and give people
`CAN_RUN` in `permissions`.

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
which uses every setting. Their data comes from `demo/`, a separate bundle you won't need for your own agents.

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
