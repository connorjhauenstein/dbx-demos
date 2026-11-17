# Genie agents as code

Manage Genie agents as small, readable files in git instead of one large `serialized_space` JSON,
and share benchmark questions across every agent that uses the same metric view.

```
agents/
  growth/
    agent.yml              # metric views + sample questions
    instructions.md        # the agent's text instruction
    examples/*.sql         # example SQL; first line is "-- question: ..."
  monetization/ ...
benchmarks/
  weekly_active_users.yml  # metric_view + questions; added to EVERY agent using that view
  subscription_metrics.yml
resources/genie_agents.yml # DAB genie_spaces resources (title, description, warehouse)
genie_as_code.py           # build | explode | evaluate
```

`{schema}` in the files stands for `<catalog>.<schema>`, so the same files deploy to any workspace.

## How it works

- **build**: turns the files into `.build/<agent>.geniespace.json`. It generates stable IDs,
  sorts every collection the way the API requires, splits text into line arrays, and adds each
  benchmark to every agent whose `metric_views` include the benchmark's `metric_view`.
  The DAB `genie_spaces` resources point at these files with `file_path`.
- **explode**: pulls a live agent back into the files. Edit an agent in the Genie UI, run
  `explode`, and `git diff` shows a small, reviewable change. New benchmarks go into the matching
  metric view's file, so they reach every agent that uses that view on the next deploy.
  It warns if the live agent has settings these files don't capture.
- **evaluate**: runs each agent's benchmarks with the Genie eval-runs API (Beta), prints every
  assessment, and exits non-zero unless every question is correct, so CI can gate on it.

Git is the source of truth: UI edits are fine, but they come back through `explode` and a PR,
and the next deploy makes the live agents match git.

## Deploy

```bash
export DATABRICKS_CONFIG_PROFILE=<profile>
export BUNDLE_VAR_catalog=<catalog>          # schema defaults to genie_as_code
SCHEMA=$BUNDLE_VAR_catalog.genie_as_code

databricks bundle deploy                     # first run: creates the setup job (agents fail until data exists)
databricks bundle run setup_demo_data        # demo tables + 3 metric views
python genie_as_code.py build --schema $SCHEMA
databricks bundle deploy                     # creates or updates the Genie agents
python genie_as_code.py evaluate
```

Requires Databricks CLI ≥ 1.17 (the `genie_spaces` resource uses the direct deployment engine),
`pip install databricks-sdk pyyaml`, and a SQL warehouse (default: "Serverless Starter Warehouse").

## Day-to-day

| Change | Do this |
|---|---|
| Add a metric view to an agent | Add it to `agents/<agent>/agent.yml`, then build and deploy |
| Add a benchmark for a metric | Add it to `benchmarks/<metric_view>.yml`; every agent using that view gets it |
| Add an agent | New folder in `agents/` + an entry in `resources/genie_agents.yml` (same key) |
| Someone edited an agent in the UI | `python genie_as_code.py explode <agent> --schema $SCHEMA`, review `git diff`, open a PR |
| CI on a pull request | `build`, `databricks bundle deploy -t <target>`, then `evaluate` |

## Limits

- Covers metric views, sample questions, one text instruction, example SQL, and benchmarks.
  Other settings (join specs, SQL snippets, column configs, plain tables) aren't in the files;
  `explode` warns when a live agent has them.
- Metric views must exist before an agent that uses them is deployed.
- The eval-runs API is Beta.
