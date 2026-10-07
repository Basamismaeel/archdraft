"""Generated results as JSON files in ./data. No database in v1."""

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from archdraft import config

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


class ProjectSummary(BaseModel):
    id: str
    created_at: str
    mode: str
    system_name: str
    coverage_percent: float
    error_count: int


def data_dir() -> Path:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return config.DATA_DIR


def save(project_id: str, payload: dict[str, Any]) -> None:
    if not _SAFE_ID.match(project_id):
        raise ValueError(f"Unsafe project id: {project_id!r}")
    path = data_dir() / f"{project_id}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load(project_id: str) -> dict[str, Any] | None:
    if not _SAFE_ID.match(project_id):
        return None
    path = data_dir() / f"{project_id}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_projects() -> list[ProjectSummary]:
    summaries: list[ProjectSummary] = []
    for path in data_dir().glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            model = data.get("model") or {}
            summaries.append(
                ProjectSummary(
                    id=path.stem,
                    created_at=data.get("created_at", ""),
                    mode=data.get("mode", ""),
                    system_name=model.get("system_name") or "(baseline diagram)",
                    coverage_percent=data.get("coverage", {}).get("percent", 0.0),
                    error_count=len(data.get("validation_errors", [])),
                )
            )
        except (OSError, ValueError, AttributeError):
            continue  # a hand-edited or partial file should not break the list
    return sorted(summaries, key=lambda s: s.created_at, reverse=True)
