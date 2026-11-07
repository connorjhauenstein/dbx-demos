"""Which metric views this MCP exposes, read from config.yml."""

from pathlib import Path

import yaml

CONFIG = Path(__file__).resolve().parent.parent / "config.yml"


def load_include(path: Path = CONFIG) -> list[str]:
    return [str(entry).strip().lower() for entry in yaml.safe_load(path.read_text())["include"]]


def in_scope(full_name: str, include: list[str]) -> bool:
    """True if `catalog.schema.view` matches "*", its catalog, its schema, or itself."""
    parts = full_name.lower().split(".")
    return any(entry == "*" or parts[: entry.count(".") + 1] == entry.split(".") for entry in include)
