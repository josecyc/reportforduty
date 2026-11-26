#!/usr/bin/env python3
"""Write lean/ReportForDuty/Statements/*.lean from programs/*.json and build them.

Run after editing a program. Every statement must elaborate against the definitions, or
the build fails and names the step.
  python3 tools/gen_statements.py           write and build
  python3 tools/gen_statements.py --no-build
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rfd import registry  # noqa: E402


def main() -> int:
    steps = registry.all_steps()
    registry.STATEMENTS_DIR.mkdir(parents=True, exist_ok=True)
    wanted = set()
    for step in steps.values():
        path = registry.STATEMENTS_DIR / f"{step.lean}.lean"
        wanted.add(path.name)
        text = step.statement_file()
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
    for old in registry.STATEMENTS_DIR.glob("*.lean"):
        if old.name not in wanted:
            old.unlink()
    index = registry.LEAN_DIR / "ReportForDuty" / "Statements.lean"
    index.write_text(
        "\n".join(f"import ReportForDuty.Statements.{s.lean}" for s in sorted(steps.values(), key=lambda s: s.id)) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(steps)} statement files")
    if "--no-build" in sys.argv:
        return 0
    r = subprocess.run(["lake", "build", "ReportForDuty.Statements"], cwd=registry.LEAN_DIR,
                       capture_output=True, text=True)
    errors = [l for l in (r.stdout + r.stderr).splitlines() if "error" in l.lower()]
    if r.returncode != 0:
        print("\n".join(errors[:40]) or (r.stdout + r.stderr)[-4000:])
        print("build FAILED")
        return 1
    print("all statements elaborate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
