"""The judge. A step counts only when this accepts a proof (or a refutation) of it.

    python3 -m rfd.checker STEP-ID path/to/file.lean

What it does, in order:
1. Format rules (rfd/rules.py), read by a program before anything builds.
2. Compiles the file as its own module in a fresh temporary folder, inside a macOS sandbox
   with no network, no writes outside that folder and no reading of file contents in the home
   folder outside the Lean project and toolchain, under a time and memory limit.
3. Compiles a separate check file that imports the posted statement, which was elaborated
   from programs/*.json without the submission in scope, and the submission, and requires
   `theorem RFDCheck : <statement> := <submitted theorem>` to type-check. A proof of a
   stronger, weaker or reworded statement fails here unless it is definitionally the same.
4. Requires the check theorem to depend on no axioms beyond propext, Classical.choice and
   Quot.sound. A sorry or native_decide anywhere would show up here.

What it cannot decide: whether the Lean statement says what its plain sentence says.
That is a human's job, recorded per program as `reviewed`.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

from . import registry, rules

STANDARD_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}
TIME_LIMIT = int(os.environ.get("RFD_TIME_LIMIT", "600"))
MEMORY_LIMIT_KB = int(float(os.environ.get("RFD_MEMORY_GB", "6")) * 1024 * 1024)


@dataclass
class Verdict:
    step: str
    verdict: str  # ACCEPTED | REJECTED | FAULT
    kind: str | None = None  # prove | refute
    reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    axioms: list[str] = field(default_factory=list)
    log: str = ""
    seconds: float = 0.0

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


@lru_cache(maxsize=1)
def lean_env() -> tuple[str, str]:
    """(path to the real lean binary, LEAN_PATH) for the pinned project."""
    lean = subprocess.run(["elan", "which", "lean"], cwd=registry.LEAN_DIR, capture_output=True,
                          text=True, check=True).stdout.strip()
    lean_path = subprocess.run(["lake", "env", "printenv", "LEAN_PATH"], cwd=registry.LEAN_DIR,
                               capture_output=True, text=True, check=True).stdout.strip()
    return lean, lean_path


def sandbox_profile(work: Path, lean_bin: str) -> str:
    home = str(Path.home())
    toolchain = str(Path(lean_bin).resolve().parent.parent)
    return f"""(version 1)
(allow default)
(deny network*)
(deny file-write*)
(allow file-write* (subpath "{work}") (literal "/dev/null"))
(deny file-read-data (subpath "{home}"))
(allow file-read-data (subpath "{registry.LEAN_DIR}") (subpath "{toolchain}") (subpath "{work}"))
"""


def run_limited(cmd: list[str], cwd: Path, env: dict, timeout: int) -> tuple[int | None, str, str]:
    """Run cmd; returns (exit code or None, output, reason when killed)."""
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    killed = {"why": ""}

    def watch():
        start = time.time()
        while proc.poll() is None:
            if time.time() - start > timeout:
                killed["why"] = f"over the time limit of {timeout} s"
                proc.kill()
                return
            try:
                rss = int(subprocess.run(["ps", "-o", "rss=", "-p", str(proc.pid)],
                                         capture_output=True, text=True).stdout.strip() or 0)
            except ValueError:
                rss = 0
            if rss > MEMORY_LIMIT_KB:
                killed["why"] = f"over the memory limit of {MEMORY_LIMIT_KB // 1048576} GB"
                proc.kill()
                return
            time.sleep(0.5)

    t = threading.Thread(target=watch, daemon=True)
    t.start()
    out, _ = proc.communicate()
    t.join(timeout=2)
    return (None if killed["why"] else proc.returncode), out or "", killed["why"]


def error_lines(out: str, work: Path, limit: int = 25) -> str:
    keep = []
    for line in out.splitlines():
        line = line.replace(str(work) + "/", "")
        keep.append(line)
    text = "\n".join(keep)
    return text[-6000:] if len(text) > 6000 else text


def submitted_kind(body: str, lean: str) -> tuple[str | None, str | None]:
    prove = re.search(rf"\btheorem\s+{lean}(?![\w'])", body)
    refute = re.search(rf"\btheorem\s+{lean}_refute(?![\w'])", body)
    if prove and refute:
        return None, f"declare either theorem {lean} or theorem {lean}_refute, not both"
    if not prove and not refute:
        return None, (f"no theorem {lean} (a proof) or {lean}_refute (a refutation) found; "
                      "keep the name from the skeleton, inside namespace ReportForDuty.Steps")
    return ("refute" if refute else "prove"), None


def check(step_id: str, src: bytes, keep_dir: bool = False) -> Verdict:
    t0 = time.time()
    steps = registry.all_steps()
    step = steps.get(step_id)
    if step is None:
        return Verdict(step_id, "REJECTED", reasons=[f"no step {step_id}"])
    merged = registry.merged_modules() - {step.module}

    def allowed(mod: str) -> bool:
        return (mod == "Mathlib" or mod.startswith("Mathlib.") or mod.startswith("ReportForDuty.Defs.")
                or mod in merged)

    refusals, notes, body = rules.check(src, allowed)
    v = Verdict(step_id, "REJECTED", notes=notes)
    if refusals:
        v.reasons = refusals
        v.seconds = round(time.time() - t0, 2)
        return v
    kind, problem = submitted_kind(body, step.lean)
    if problem:
        v.reasons = [problem]
        return v
    v.kind = kind

    lean_bin, lean_path = lean_env()
    work = Path(tempfile.mkdtemp(prefix="rfd-check-")).resolve()
    try:
        (work / "RFDSub").mkdir()
        sub = work / "RFDSub" / f"{step.lean}.lean"
        sub.write_bytes(src)
        profile = work / "sandbox.sb"
        profile.write_text(sandbox_profile(work, lean_bin))
        env = {"PATH": "/usr/bin:/bin", "LEAN_PATH": f"{lean_path}:{work}", "HOME": str(work),
               "TMPDIR": str(work), "LANG": "C.UTF-8"}
        sandbox = ["sandbox-exec", "-f", str(profile)]

        code, out, why = run_limited(
            sandbox + [lean_bin, "-R", str(work), "-o", str(work / "RFDSub" / f"{step.lean}.olean"), str(sub)],
            work, env, TIME_LIMIT)
        if why:
            v.verdict, v.reasons, v.log = "FAULT", [f"compiling the file ran {why}; this says nothing about the proof"], error_lines(out, work)
            return v
        if code != 0:
            v.reasons = ["the file does not compile"]
            v.log = error_lines(out, work)
            return v

        target = f"¬ ReportForDuty.Statements.{step.lean}" if kind == "refute" else f"ReportForDuty.Statements.{step.lean}"
        theorem = step.refute_theorem if kind == "refute" else step.theorem
        check_file = work / "RFDCheck.lean"
        check_file.write_text(
            f"import {step.statement_module}\nimport RFDSub.{step.lean}\n\n"
            f"theorem RFDCheck : {target} := {theorem}\n\n#print axioms RFDCheck\n",
            encoding="utf-8")
        code, out2, why = run_limited(sandbox + [lean_bin, str(check_file)], work, env, TIME_LIMIT)
        if why:
            v.verdict, v.reasons = "FAULT", [f"the statement check ran {why}"]
            return v
        if code != 0:
            v.reasons = [f"{theorem} does not prove exactly the posted statement"
                         + (" (its negation)" if kind == "refute" else "")]
            v.log = error_lines(out2, work)
            return v
        m = re.search(r"'RFDCheck' depends on axioms: \[([^\]]*)\]", out2)
        axioms = [a.strip() for a in m.group(1).split(",")] if m else []
        if not m and "does not depend on any axioms" not in out2:
            v.verdict, v.reasons, v.log = "FAULT", ["could not read the axiom report"], error_lines(out2, work)
            return v
        v.axioms = axioms
        extra = [a for a in axioms if a not in STANDARD_AXIOMS]
        if extra:
            v.reasons = ["the proof depends on axioms beyond the standard three: " + ", ".join(extra)]
            return v
        v.verdict = "ACCEPTED"
        v.log = error_lines(out, work)
        return v
    finally:
        v.seconds = round(time.time() - t0, 2)
        if not keep_dir:
            shutil.rmtree(work, ignore_errors=True)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python3 -m rfd.checker STEP-ID FILE", file=sys.stderr)
        return 2
    v = check(argv[0], Path(argv[1]).read_bytes())
    print(f"{v.verdict} {v.step}" + (f" ({v.kind})" if v.kind else "") + f" in {v.seconds} s")
    for r in v.reasons:
        print(f"  reason: {r}")
    for n in v.notes:
        print(f"  note: {n}")
    if v.verdict != "ACCEPTED" and v.log:
        print(v.log)
    return 0 if v.verdict == "ACCEPTED" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
