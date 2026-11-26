"""The step registry: programs/*.json, and the Lean files generated from it.

A program is a line of work (for example the off-switch game). A step is one exact Lean
statement inside a program. The statement text in programs/*.json is the single source of
truth: the checker elaborates it in its own file, apart from any submission, and a proof
counts only if its type is that statement.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEAN_DIR = ROOT / "lean"
PROGRAMS_DIR = ROOT / "programs"
STATEMENTS_DIR = LEAN_DIR / "ReportForDuty" / "Statements"
STEPS_DIR = LEAN_DIR / "ReportForDuty" / "Steps"

POINTS = {"warmup": 1, "solid": 3, "hard": 8, "open": 20}
LEVELS = list(POINTS)
STEP_ID = re.compile(r"^[A-Z]{1,6}-\d{2,3}$")
LEAN_NAME = re.compile(r"^[A-Z]{1,6}\d{2,3}$")


@dataclass
class Step:
    id: str
    lean: str
    title: str
    statement: str
    level: str
    context: str
    sketch: str
    program: "Program" = field(repr=False)

    @property
    def points(self) -> int:
        return POINTS[self.level]

    @property
    def module(self) -> str:
        return f"ReportForDuty.Steps.{self.lean}"

    @property
    def file(self) -> str:
        return f"lean/ReportForDuty/Steps/{self.lean}.lean"

    @property
    def statement_module(self) -> str:
        return f"ReportForDuty.Statements.{self.lean}"

    @property
    def theorem(self) -> str:
        return f"ReportForDuty.Steps.{self.lean}"

    @property
    def refute_theorem(self) -> str:
        return f"ReportForDuty.Steps.{self.lean}_refute"

    def header(self) -> str:
        """Imports and opens shared by the statement file and the skeleton."""
        lines = [f"import {self.program.defs}", ""]
        for ns in self.program.open:
            lines.append(f"open {ns}")
        lines.append("open Classical")
        return "\n".join(lines)

    def statement_file(self) -> str:
        return (
            f"{self.header()}\n\n"
            f"/-! Generated from programs/{self.program.id}.json by tools/gen_statements.py.\n"
            f"Do not edit by hand. -/\n\n"
            f"namespace ReportForDuty.Statements\n\n"
            f"/-- {self.id}: {self.title} -/\n"
            f"def {self.lean} : Prop :=\n  {self.statement}\n\n"
            f"end ReportForDuty.Statements\n"
        )

    def skeleton(self, refute: bool = False) -> str:
        name = f"{self.lean}_refute" if refute else self.lean
        stmt = f"¬ ({self.statement})" if refute else self.statement
        what = "a refutation of" if refute else "a proof of"
        return (
            f"{self.header()}\n\n"
            f"/-! {self.id}, {what} the posted statement.\n"
            f"{self.title}\n"
            f"Prove exactly this statement. Helpers go in this file. -/\n\n"
            f"namespace ReportForDuty.Steps\n\n"
            f"theorem {name} :\n    {stmt} := by\n  sorry\n\n"
            f"end ReportForDuty.Steps\n"
        )

    def public(self) -> dict:
        return {
            "id": self.id,
            "lean": self.lean,
            "program": self.program.id,
            "title": self.title,
            "statement": self.statement,
            "level": self.level,
            "points": self.points,
            "context": self.context,
            "sketch": self.sketch,
            "file": self.file,
            "module": self.module,
            "imports": [self.program.defs],
            "theorem": self.theorem,
            "refute_theorem": self.refute_theorem,
        }


@dataclass
class Program:
    id: str
    prefix: str
    name: str
    question: str
    summary: str
    why: str
    source: dict | None
    defs: str
    open: list[str]
    reviewed: bool
    hidden: bool
    steps: list[Step]

    def public(self) -> dict:
        return {
            "id": self.id,
            "prefix": self.prefix,
            "name": self.name,
            "question": self.question,
            "summary": self.summary,
            "why": self.why,
            "source": self.source,
            "defs": self.defs,
            "reviewed": self.reviewed,
        }


def load() -> dict[str, Program]:
    programs: dict[str, Program] = {}
    seen_steps: set[str] = set()
    for path in sorted(PROGRAMS_DIR.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("kind") in ("frontier", "audit", "intel", "wargame"):
            continue  # other mission kinds have their own loaders
        prog = Program(
            id=raw["id"], prefix=raw["prefix"], name=raw["name"], question=raw["question"],
            summary=raw["summary"], why=raw.get("why", ""), source=raw.get("source"),
            defs=raw["defs"], open=raw.get("open", []), reviewed=bool(raw.get("reviewed")),
            hidden=bool(raw.get("hidden")), steps=[],
        )
        for s in raw["steps"]:
            step = Step(
                id=s["id"], lean=s["lean"], title=s["title"], statement=s["statement"],
                level=s["level"], context=s.get("context", ""), sketch=s.get("sketch", ""),
                program=prog,
            )
            problems = validate_step(step)
            if problems:
                raise ValueError(f"{path.name} {step.id}: " + "; ".join(problems))
            if step.id in seen_steps:
                raise ValueError(f"duplicate step id {step.id}")
            seen_steps.add(step.id)
            prog.steps.append(step)
        programs[prog.id] = prog
    return programs


def validate_step(step: Step) -> list[str]:
    problems = []
    if not STEP_ID.match(step.id):
        problems.append("id must look like OSG-01")
    if not LEAN_NAME.match(step.lean) or step.lean != step.id.replace("-", ""):
        problems.append("lean name must be the id without the hyphen")
    if step.level not in POINTS:
        problems.append(f"level must be one of {LEVELS}")
    if '"' in step.statement:
        problems.append("statements may not contain double quotes")
    return problems


def all_steps(include_hidden: bool = True) -> dict[str, Step]:
    out: dict[str, Step] = {}
    for prog in load().values():
        if prog.hidden and not include_hidden:
            continue
        for step in prog.steps:
            out[step.id] = step
    return out


def merged_modules() -> set[str]:
    """Accepted proofs already merged into lean/ReportForDuty/Steps."""
    if not STEPS_DIR.exists():
        return set()
    return {f"ReportForDuty.Steps.{p.stem}" for p in STEPS_DIR.glob("*.lean")}
