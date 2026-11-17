"""A job and an MLflow experiment for each folder in tasks/, built at deploy time.

The job runs the task with the harness and model from its task.yml, on its schedule, with its tags. Override them per
run with --params harness=...,model=... to compare. Every run of a task lands in its experiment, with traces in Unity Catalog.
"""
from pathlib import Path

import yaml
from databricks.bundles.core import Bundle, Resources
from databricks.bundles.experiments import MlflowExperiment
from databricks.bundles.jobs import Job

TASKS = sorted(p for p in (Path(__file__).parent.parent / "tasks").iterdir() if p.is_dir())
EXPERIMENTS = "${workspace.root_path}/traces-"  # experiment per task: <EXPERIMENTS><task>


def load_resources(bundle: Bundle) -> Resources:
    resources = Resources()
    for task in TASKS:
        config = yaml.safe_load((task / "task.yml").read_text())
        key = task.name.replace("-", "_")
        resources.add_mlflow_experiment(
            key,
            MlflowExperiment.from_dict(
                {
                    "name": f"{EXPERIMENTS}{task.name}",
                    "trace_location": {
                        "uc_trace_location": {"catalog": "${var.trace_catalog}", "schema": "${var.trace_schema}", "table_prefix": key}
                    },
                    "permissions": [{"service_principal_name": "${var.service_principal}", "level": "CAN_EDIT"}],
                }
            ),
        )
        resources.add_job(
            key,
            Job.from_dict(
                {
                    "name": f"agent-task-{task.name}",
                    "run_as": {"service_principal_name": "${var.service_principal}"},
                    "tags": {"task": task.name} | config.get("tags", {}),
                    "parameters": [
                        {"name": "harness", "default": config["harness"]},
                        {"name": "model", "default": config["model"]},
                    ],
                    "environments": [
                        {"environment_key": "default", "spec": {"client": "4", "dependencies": ["pyyaml", "mlflow-skinny>=3.14"]}}
                    ],
                    "tasks": [
                        {
                            "task_key": "run_agent",
                            "environment_key": "default",
                            "spark_python_task": {
                                "python_file": "src/run_task.py",
                                "parameters": [
                                    "${workspace.file_path}",
                                    task.name,
                                    "{{job.parameters.harness}}",
                                    "{{job.parameters.model}}",
                                    EXPERIMENTS,
                                    "{{job.run_id}}",
                                ],
                            },
                        }
                    ],
                }
                | ({"schedule": config["schedule"]} if "schedule" in config else {})
            ),
        )
    return resources
