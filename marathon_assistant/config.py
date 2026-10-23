"""Load shared project settings and resolve paths relative to the project root."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import tomllib
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = PROJECT_ROOT / "config.toml"


@lru_cache(maxsize=1)
def load_project_config() -> dict[str, Any]:
    """Read the project's TOML configuration once per process."""
    with CONFIG_FILE.open("rb") as config_file:
        return tomllib.load(config_file)


def resolve_project_path(path: str | Path) -> Path:
    """Return an absolute path, resolving relative paths from the project root."""
    path = Path(path)
    return path if path.is_absolute() else PROJECT_ROOT / path
