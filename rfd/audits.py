"""The backdoor-audit track: models to audit, and helpers. The judge is rfd/nets/audit.py."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache

from .registry import PROGRAMS_DIR, ROOT

AUDIT_ID = re.compile(r"^A\d{1,3}$")
MAX_SUBMISSION_BYTES = 64 * 1024 * 1024


@dataclass
class AuditProgram:
    id: str
    name: str
    question: str
    summary: str
    why: str
    sources: list
    models: str
    points: int
    season: str

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "question": self.question, "summary": self.summary,
                "why": self.why, "sources": self.sources, "points": self.points, "season": self.season, "kind": "audit"}


@dataclass
class AuditTarget:
    id: str
    program: AuditProgram

    @property
    def model_file(self) -> str:
        return f"{self.program.models}/{self.id}.npz"

    def public(self) -> dict:
        from .nets import audit
        return {"id": self.id, "model_file": self.model_file, "program": self.program.id, "k": 10, "V": 64,
                "region_min": audit.REGION_MIN, "trigger_rate": audit.TRIGGER_RATE,
                "trigger_samples": audit.TRIGGER_SAMPLES, "max_trigger_positions": audit.MAX_TRIGGER_POSITIONS,
                "clean_slack": str(audit.clean_slack(10, 64)), "region_inputs": str(audit.region_size(10, 64)),
                "points": self.program.points}


@lru_cache(maxsize=1)
def load() -> AuditProgram | None:
    for path in sorted(PROGRAMS_DIR.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("kind") == "audit":
            return AuditProgram(raw["id"], raw["name"], raw["question"], raw["summary"], raw.get("why", ""),
                                raw.get("sources", []), raw["models"], int(raw.get("points", 40)), raw.get("season", ""))
    return None


@lru_cache(maxsize=1)
def targets() -> dict[str, AuditTarget]:
    prog = load()
    if not prog:
        return {}
    files = sorted((ROOT / prog.models).glob("A*.npz"), key=lambda p: int(p.stem[1:]))
    return {p.stem: AuditTarget(p.stem, prog) for p in files}


@lru_cache(maxsize=16)
def model(target_id: str):
    from .nets.maxofk import MaxOfK
    t = targets()[target_id]
    m = MaxOfK.load(ROOT / t.model_file)
    m.name = target_id
    return m
