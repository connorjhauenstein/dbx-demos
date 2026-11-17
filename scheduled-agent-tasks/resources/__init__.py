"""Jobs built from the repo at deploy time.

- One job per file in tasks/: runs the task with the agent named in its frontmatter, on its schedule, with its tags.
- One MLflow experiment per task, with traces stored in Unity Catalog: every run of the task, from any agent, lands there.
- One compare_agents job: runs any task with every agent in agents/, in parallel, for side-by-side results.
"""
from pathlib import Path

import yaml
from databricks.bundles.core import Bundle, Resources
from databricks.bundles.experiments import MlflowExperiment
from databricks.bundles.jobs import Job

ROOT = Path(__file__).parent.parent
EXPERIMENTS = "${workspace.root_path}/traces-"  # experiment per task: <EXPERIMENTS><task>
TASKS = sorted((ROOT / "tasks").glob("*.md"))
AGENTS = sorted(p.stem for p in (ROOT / "agents").glob("*.yml"))


def run_agent(task_key: str, agent: str) -> dict:
    return {
        "task_key": task_key,
        "environment_key": "default",
        "spark_python_task": {
            "python_file": "src/run_task.py",
            "parameters": [
                "${workspace.file_path}",
                "{{job.parameters.task}}",
                agent,
                "${var.platform_schema}",
                EXPERIMENTS,
                "{{job.run_id}}",
            ],
        },
    }


def job(name: str, parameters: list[dict], tasks: list[dict], **extra) -> Job:
    return Job.from_dict(
        {
            "name": name,
            "run_as": {"service_principal_name": "${var.service_principal}"},
            "parameters": parameters,
            "environments": [
                {"environment_key": "default", "spec": {"client": "4", "dependencies": ["pyyaml", "mlflow-skinny>=3.14"]}}
            ],
            "tasks": tasks,
            **extra,
        }
    )


def load_resources(bundle: Bundle) -> Resources:
    resources = Resources()
    for path in TASKS:
        meta = yaml.safe_load(path.read_text().split("---", 2)[1])
        resources.add_mlflow_experiment(
            path.stem.replace("-", "_"),
            MlflowExperiment.from_dict(
                {
                    "name": f"{EXPERIMENTS}{path.stem}",
                    "trace_location": {
                        "uc_trace_location": {
                            "catalog": "${var.trace_catalog}",
                            "schema": "${var.trace_schema}",
                            "table_prefix": path.stem.replace("-", "_"),
                        }
                    },
                    "permissions": [{"service_principal_name": "${var.service_principal}", "level": "CAN_EDIT"}],
                }
            ),
        )
        extra = {"tags": {"task": path.stem} | meta.get("tags", {})}
        if "schedule" in meta:
            extra["schedule"] = meta["schedule"]
        resources.add_job(
            path.stem.replace("-", "_"),
            job(
                f"agent-task-{path.stem}",
                [{"name": "task", "default": path.stem}, {"name": "agent", "default": meta["agent"]}],
                [run_agent("run_agent", "{{job.parameters.agent}}")],
                **extra,
            ),
        )
    resources.add_job(
        "compare_agents",
        job(
            "agent-task-compare",
            [{"name": "task", "default": TASKS[0].stem}],
            [run_agent(agent.replace("-", "_"), agent) for agent in AGENTS],
        ),
    )
    return resources
