"""Config loading. Values live in config.toml at the repo root."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_cache = None


def load(reload=False):
    global _cache
    if _cache is None or reload:
        with open(ROOT / "config.toml", "rb") as f:
            _cache = tomllib.load(f)
    return _cache


def path(key):
    """Resolve a config path value against the repo root."""
    cfg = load()
    for section in cfg.values():
        if isinstance(section, dict) and key in section:
            return ROOT / section[key]
    raise KeyError(key)
