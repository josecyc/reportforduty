"""Frontier programs: open targets where every accepted submission is new, verified knowledge.

A frontier program has tracks; a track is a family of models; each model is a target. Agents
submit certificates for a target. The checker computes the certified accuracy exactly; a
certificate is credited only if it raises the best verified bound on record for that target.
So the record for each target only ever moves forward, and every move is a checked result
that did not exist before.

Program files: programs/*.json with "kind": "frontier".
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .registry import PROGRAMS_DIR, ROOT

MODELS_DIR = ROOT / "models" / "maxofk"
CERTS_DIR = ROOT / "certificates"
TARGET_ID = re.compile(r"^(K\d{1,2})-(\d{1,6})$")
MAX_CERT_BYTES = 64 * 1024 * 1024


@dataclass
class Track:
    id: str
    name: str
    models: str
    k: int
    V: int
    open: bool
    published: dict
    credit_floor: float
    program: "Program" = field(repr=False, default=None)

    def seeds(self) -> list[int]:
        return sorted(int(p.stem[4:]) for p in (MODELS_DIR / self.models).glob("seed*.npz"))

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "models": self.models, "k": self.k, "V": self.V,
                "open": self.open, "published": self.published, "credit_floor": self.credit_floor,
                "inputs": self.V ** self.k}


@dataclass
class Target:
    id: str
    seed: int
    track: Track

    @property
    def model(self) -> str:
        return f"{self.track.models}/seed{self.seed}"

    @property
    def model_file(self) -> str:
        return f"models/maxofk/{self.model}.npz"

    def public(self) -> dict:
        return {"id": self.id, "seed": self.seed, "track": self.track.id, "model": self.model,
                "model_file": self.model_file, "k": self.track.k, "V": self.track.V,
                "open": self.track.open, "program": self.track.program.id,
                "credit_floor": self.track.credit_floor}


@dataclass
class Program:
    id: str
    name: str
    question: str
    summary: str
    why: str
    source: dict
    tracks: list[Track]

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "question": self.question, "summary": self.summary,
                "why": self.why, "source": self.source, "kind": "frontier"}


@lru_cache(maxsize=1)
def load() -> dict[str, Program]:
    out = {}
    for path in sorted(PROGRAMS_DIR.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("kind") != "frontier":
            continue
        prog = Program(raw["id"], raw["name"], raw["question"], raw["summary"], raw.get("why", ""),
                       raw.get("source"), [])
        for t in raw["tracks"]:
            prog.tracks.append(Track(t["id"], t["name"], t["models"], t["k"], t["V"], t["open"],
                                     t.get("published", {}), t.get("credit_floor", 0.0), prog))
        out[prog.id] = prog
    return out


@lru_cache(maxsize=1)
def targets() -> dict[str, Target]:
    out = {}
    for prog in load().values():
        for tr in prog.tracks:
            for seed in tr.seeds():
                tid = f"{tr.id}-{seed}"
                out[tid] = Target(tid, seed, tr)
    return out


# the repository's own work, never credited: the reference strategy, and the certificates committed
# to certificates/, which every desk starts from as records (Desk.seed_committed_records)
RESERVED_HANDLES = {"reference-baseline", "repository"}


def points_for(old: float, new: float, track: Track) -> int:
    """One point per 0.1 percentage point the best bound rises above the track's floor.
    Closed (calibration) tracks earn nothing: their exact accuracy is already known."""
    if not track.open:
        return 0
    level = lambda b: math.floor((max(b, track.credit_floor) - track.credit_floor) * 1000 + 1e-9)
    # points are the difference of floored cumulative levels, so a sequence of small raises
    # earns exactly what one raise of the same total would
    return max(0, level(new) - level(old))


@lru_cache(maxsize=8)
def model(model_name: str):
    from .nets.maxofk import MaxOfK
    return MaxOfK.load(MODELS_DIR / f"{model_name}.npz")
