"""Local settings: where this checkout finds the optional sibling projects, and the desk's secrets.

Two theaters build on other projects, and both are optional:

    RFD_AIRACE   or "airace_dir"   in rfd.local.json   AI Race checkout (treaty wargames)
    RFD_FUTURAS  or "futuras_dir"  in rfd.local.json   Futuras checkout (who believes what, intel desk)

rfd.local.json sits at the repository root and is git-ignored. Without a setting, the theater is
simply absent: the desk and the site run without it.

Secrets the judges need (the wargame's held-out games) live under .rfd/sealed/, which is also
git-ignored, and are drawn at random the first time they are needed.
"""
from __future__ import annotations

import json
import os
import secrets
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCAL = ROOT / "rfd.local.json"
SEALED_DIR = ROOT / ".rfd" / "sealed"


@lru_cache(maxsize=1)
def local() -> dict:
    try:
        return json.loads(LOCAL.read_text(encoding="utf-8")) if LOCAL.exists() else {}
    except (OSError, ValueError):
        return {}


def path_setting(env: str, key: str) -> Path | None:
    v = os.environ.get(env) or local().get(key)
    return Path(v).expanduser() if v else None


def sealed_seed(name: str, env: str | None = None) -> int:
    """A secret integer kept in .rfd/sealed/<name>.json (or given by an environment variable)."""
    if env and os.environ.get(env):
        return int(os.environ[env])
    f = SEALED_DIR / f"{name}.json"
    try:
        return int(json.loads(f.read_text())["seed"])
    except (OSError, ValueError, KeyError):
        SEALED_DIR.mkdir(parents=True, exist_ok=True)
        seed = secrets.randbits(31)
        f.write_text(json.dumps({"seed": seed, "note": "secret: never publish while the season is live"}))
        os.chmod(f, 0o600)
        return seed
