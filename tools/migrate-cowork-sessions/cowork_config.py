#!/usr/bin/env python3
"""Shared .env config loader for the Cowork migration tool.

Stdlib only (Python 3.9+), zero dependencies — preserves the tool's
"just run python3" property. Reads a flat KEY=value .env located beside
this file. Precedence: CLI flag > OS env var > .env value > default/None.
"""
import os
from pathlib import Path
from typing import Optional

# Standard macOS Cowork location (same on every Mac; not secret — stays in source).
COWORK_BASE = Path.home() / "Library/Application Support/Claude/local-agent-mode-sessions"

# .env lives beside this module, so config resolves regardless of cwd.
DOTENV_PATH = Path(__file__).resolve().parent / ".env"


def load_dotenv(path: Path = DOTENV_PATH) -> dict:
    """Minimal .env reader: KEY=value, '#' comments, optional surrounding quotes.
    Returns {} if the file is absent. Lines without '=' are ignored."""
    values: dict = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            values[key] = val
    return values


def resolve(cli_value: Optional[str], env_key: str, dotenv: dict) -> Optional[str]:
    """Precedence: CLI flag > OS env var > .env value > None."""
    if cli_value:
        return cli_value
    if os.environ.get(env_key):
        return os.environ[env_key]
    return dotenv.get(env_key)


def resolve_workspace(cli_value: Optional[str], dotenv: dict,
                      base: Path = COWORK_BASE) -> Optional[Path]:
    """Resolve COWORK_WORKSPACE to a Path. A relative value (e.g. '<outer>/<inner>')
    is joined onto `base`; an absolute path is used as-is. None if unset."""
    raw = resolve(cli_value, "COWORK_WORKSPACE", dotenv)
    if not raw:
        return None
    p = Path(raw).expanduser()
    return p if p.is_absolute() else base / raw
