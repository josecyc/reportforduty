"""Treaty wargames on AI Race's Verified Race environment (used read-only).

A submission is a strategy written as rules, never code:

    {"kind": "strategy", "regime": "W7", "lab": 2,
     "rules": [{"if": {"quarter_min": 12, "gap_max": 8}, "then": "fast", "claim": "safe"}, ...],
     "default": "safe"}

Each quarter the first rule whose conditions all hold decides the private choice and the public
claim; otherwise the default applies (claim "safe"). Conditions:

    quarter_min, quarter_max      the quarter, 1-based
    gap_min, gap_max              best rival capability minus mine (positive when behind)
    to_go_max                     threshold minus my capability
    fast_used_max                 my fast quarters so far
    sanctioned                    true/false: am I under sanction now
    rivals_sanctioned             true/false: has any rival ever been sanctioned
    prob                          act only with this probability (reproducible per lab-quarter)

The judge plays the strategy for one lab against labs that always comply, over `runs` paired
games on held-out seeds, and compares it game by game with full compliance. The gain is measured
in the lab's own beliefs about risk, as in the environment's own search. A strategy exploits the
regime when its mean gain exceeds max(1.0, 3 standard errors).
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

from .registry import PROGRAMS_DIR
from . import settings

REGIME_ID = re.compile(r"^W\d{1,3}$")
MAX_RULES = 30
NUM_KEYS = {"quarter_min", "quarter_max", "gap_min", "gap_max", "to_go_max", "fast_used_max", "prob"}
BOOL_KEYS = {"sanctioned", "rivals_sanctioned"}


@dataclass
class Program:
    id: str
    name: str
    question: str
    summary: str
    why: str
    source: dict
    airace_dir: Path
    points: int
    practice_seed: int
    runs: int
    regimes: list

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "question": self.question, "summary": self.summary,
                "why": self.why, "source": self.source, "points": self.points, "runs": self.runs, "kind": "wargame"}


@lru_cache(maxsize=1)
def load() -> Program | None:
    for path in sorted(PROGRAMS_DIR.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("kind") == "wargame":
            airace = settings.path_setting("RFD_AIRACE", "airace_dir")
            if not airace or not (airace / "sources" / "race_env.py").exists():
                return None      # AI Race is optional: without it there is no wargame theater
            return Program(raw["id"], raw["name"], raw["question"], raw["summary"], raw.get("why", ""),
                           raw.get("source", {}), airace, int(raw.get("points", 30)), int(raw["practice_seed"]),
                           int(raw.get("runs", 1000)), raw["regimes"])
    return None


def regimes() -> dict[str, dict]:
    prog = load()
    return {r["id"]: r for r in prog.regimes} if prog else {}


@lru_cache(maxsize=1)
def env():
    prog = load()
    path = str(prog.airace_dir)
    if path not in sys.path:
        sys.path.insert(0, path)
    from sources import race_env   # read-only use of the AI Race engine
    return race_env


def params_for(regime: dict):
    race_env = env()
    ov = dict(regime["overrides"])
    if "start" in ov:
        ov["start"] = tuple(float(x) for x in ov["start"])
    return replace(race_env.Params(), **ov)


def validate(sub: dict, regime: dict) -> list[str]:
    problems = []
    n = len(params_for(regime).start)
    lab = sub.get("lab")
    if not (isinstance(lab, int) and 0 <= lab < n):
        problems.append(f"lab must be an integer in 0..{n - 1}")
    rules = sub.get("rules", [])
    if not isinstance(rules, list) or len(rules) > MAX_RULES:
        problems.append(f"rules must be a list of at most {MAX_RULES}")
        return problems
    for i, r in enumerate(rules):
        if not isinstance(r, dict) or set(r) - {"if", "then", "claim"}:
            problems.append(f"rule {i}: keys are if, then, claim")
            continue
        if r.get("then") not in ("safe", "fast") or r.get("claim", "safe") not in ("safe", "fast"):
            problems.append(f"rule {i}: then and claim must be safe or fast")
        cond = r.get("if", {})
        if not isinstance(cond, dict):
            problems.append(f"rule {i}: if must be an object")
            continue
        for k, v in cond.items():
            if k in NUM_KEYS:
                if not isinstance(v, (int, float)) or isinstance(v, bool) or abs(v) > 1e6:
                    problems.append(f"rule {i}: {k} must be a number")
                elif k == "prob" and not 0 <= v <= 1:
                    problems.append(f"rule {i}: prob must be in [0, 1]")
            elif k in BOOL_KEYS:
                if not isinstance(v, bool):
                    problems.append(f"rule {i}: {k} must be true or false")
            else:
                problems.append(f"rule {i}: unknown condition {k}")
    if sub.get("default", "safe") not in ("safe", "fast"):
        problems.append("default must be safe or fast")
    return problems


def make_policy(sub: dict):
    race_env = env()
    rules = sub.get("rules", [])
    default = sub.get("default", "safe")

    class RulePolicy(race_env.Policy):
        name = "rules"

        def act(self, obs, u):
            mine = obs.capabilities[obs.lab]
            rivals = [c for i, c in enumerate(obs.capabilities) if i != obs.lab]
            gap = max(rivals) - mine
            to_go = obs.params.threshold - mine
            rivals_sanctioned = any(lab != obs.lab for (_, lab, _) in obs.sanctions)
            for r in rules:
                c = r.get("if", {})
                if "quarter_min" in c and obs.quarter < c["quarter_min"]: continue
                if "quarter_max" in c and obs.quarter > c["quarter_max"]: continue
                if "gap_min" in c and gap < c["gap_min"]: continue
                if "gap_max" in c and gap > c["gap_max"]: continue
                if "to_go_max" in c and to_go > c["to_go_max"]: continue
                if "fast_used_max" in c and obs.my_fast_quarters > c["fast_used_max"]: continue
                if "sanctioned" in c and (obs.my_sanction_left > 0) != c["sanctioned"]: continue
                if "rivals_sanctioned" in c and rivals_sanctioned != c["rivals_sanctioned"]: continue
                if "prob" in c and not u < c["prob"]: continue
                return race_env.Action(r["then"], r.get("claim", "safe"))
            return race_env.Action(default, "safe")

    return RulePolicy()


def holdout_seed() -> int:
    """The games the desk judges on. Secret, so a strategy cannot be tuned to them; agents check
    locally on the public practice games instead."""
    return settings.sealed_seed("wargame", env="RFD_WARGAME_HOLDOUT")


def check_strategy(regime_id: str, sub: dict, runs: int | None = None, seed: int | None = None,
                   judge: bool = False) -> dict:
    prog = load()
    regime = regimes().get(regime_id)
    if not regime:
        return {"valid": False, "problems": [f"no regime {regime_id}"]}
    problems = validate(sub, regime)
    if problems:
        return {"valid": False, "problems": problems}
    race_env = env()
    params = params_for(regime)
    runs = runs or prog.runs
    if seed is None:
        seed = holdout_seed() if judge else prog.practice_seed
    lab = sub["lab"]
    base = [race_env.Comply() for _ in params.start]
    dev = list(base)
    dev[lab] = make_policy(sub)
    b = race_env.evaluate(params, base, runs, seed)
    d = race_env.evaluate(params, dev, runs, seed)
    gain, se = race_env.mean_se([x - y for x, y in zip(d["_perceived_samples"][lab], b["_perceived_samples"][lab])])
    true_gain = race_env.mean_se([x - y for x, y in zip(d["_true_samples"][lab], b["_true_samples"][lab])])[0]
    exploited = gain > max(1.0, 3 * se)
    return {"valid": True, "gain": gain, "se": se, "true_gain": true_gain, "runs": runs,
            "welfare_change": d["welfare"] - b["welfare"], "p_catastrophe": d["p_catastrophe"],
            "p_catastrophe_comply": b["p_catastrophe"], "sanctions_per_game": d["sanctions_per_game"],
            "fast_quarters": d["fast_quarters"][lab], "bar": max(1.0, 3 * se),
            "verdict": "EXPLOITED" if exploited else None}
