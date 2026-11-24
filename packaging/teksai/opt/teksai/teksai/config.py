"""Per-user settings, stored in ~/.config/teksai/config.json (mode 600)."""

from __future__ import annotations

import json
import os
from pathlib import Path

DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "teksai"
FILE = DIR / "config.json"


def load() -> dict:
    try:
        return json.loads(FILE.read_text())
    except (OSError, ValueError):
        return {}


def save(data: dict) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, FILE)


def api_key() -> str:
    """The saved key wins; otherwise fall back to ANTHROPIC_API_KEY."""
    return load().get("api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
