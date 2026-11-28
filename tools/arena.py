#!/usr/bin/env python3
"""Maintain the debate arena.

    python3 tools/arena.py tally            read verdicts from GitHub issues (the "Judge a debate"
                                           form) and write arena/verdicts.json
    python3 tools/arena.py standings        print the idea and advocate ratings
    python3 tools/arena.py check <file>     re-run the machine check on a round file, for a reviewer

Tally rules: one verdict per GitHub account per debate (the earliest); accounts must be at least
30 days old when they judge; issues closed as "not planned" (spam, duplicates) are skipped;
verdicts on debates that are not finished are kept but not counted until the debate is.
arena/verdicts.json stores issue numbers, never logins: anyone can audit a verdict on GitHub.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rfd import arena  # noqa: E402

REPO = "josecyc/reportforduty"
MIN_AGE_DAYS = 30
LABELS = {"debate": "Debate", "before": "Before reading, which idea did you favor?",
          "idea": "Which idea should get the push?", "argued": "Which side argued better?",
          "why": "What decided it?"}
ANSWERS = {"the first idea": "first", "the second idea": "second", "the first side": "first",
           "the second side": "second", "even": "even", "no view": "none"}


def parse_body(body: str) -> dict:
    """Fields of a GitHub issue-form body: '### <label>' headings, each followed by its answer."""
    out, label, lines = {}, None, []
    by_label = {v.lower(): k for k, v in LABELS.items()}

    def flush():
        if label is not None:
            val = "\n".join(lines).strip()
            out[label] = "" if val == "_No response_" else val
    for line in (body or "").splitlines():
        if line.startswith("### "):
            flush()
            label, lines = by_label.get(line[4:].strip().lower()), []
        elif label is not None:
            lines.append(line)
    flush()
    out.pop(None, None)
    return out


def verdict_from(issue: dict, debates: set[str]) -> dict | None:
    f = parse_body(issue.get("body") or "")
    did = (f.get("debate") or "").strip().upper()
    if did not in debates:
        return None
    v = {"issue": issue["number"], "debate": did, "at": issue["created_at"][:10]}
    for k in ("idea", "argued", "before"):
        v[k] = ANSWERS.get((f.get(k) or "").strip().lower())
    if v["idea"] not in ("first", "second", "even") and v["argued"] not in ("first", "second", "even"):
        return None
    return v


def gh(path: str) -> list:
    r = subprocess.run(["gh", "api", "--paginate", path, "--jq", ".[]"], capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise SystemExit(f"gh api {path} failed: {r.stderr.strip()}")
    return [json.loads(line) for line in r.stdout.splitlines() if line.strip()]


def account_created(login: str, cache: dict) -> str:
    if login not in cache:
        r = subprocess.run(["gh", "api", f"users/{login}", "--jq", ".created_at"], capture_output=True, text=True, timeout=60)
        cache[login] = r.stdout.strip() if r.returncode == 0 else ""
    return cache[login]


def select(issues: list[dict], debates: set[str], created: callable, min_age_days: int = MIN_AGE_DAYS) -> tuple[list, dict]:
    """The counted verdicts, earliest per (account, debate), with a count of what was skipped and why."""
    skipped = {"not_planned": 0, "bot": 0, "young_account": 0, "unreadable": 0, "repeat": 0}
    seen, out = set(), []
    for it in sorted((i for i in issues if "pull_request" not in i), key=lambda i: (i["created_at"], i["number"])):
        user = it.get("user") or {}
        if it.get("state_reason") == "not_planned":
            skipped["not_planned"] += 1; continue
        if user.get("type") != "User":
            skipped["bot"] += 1; continue
        v = verdict_from(it, debates)
        if not v:
            skipped["unreadable"] += 1; continue
        born = created(user["login"])
        if not born or (dt.datetime.fromisoformat(it["created_at"].replace("Z", "+00:00"))
                        - dt.datetime.fromisoformat(born.replace("Z", "+00:00"))).days < min_age_days:
            skipped["young_account"] += 1; continue
        key = (user["login"].lower(), v["debate"])
        if key in seen:
            skipped["repeat"] += 1; continue
        seen.add(key)
        out.append(v)
    return out, skipped


def cmd_tally(a) -> int:
    cfg = arena.load()
    debates = {d["id"] for d in cfg["debates"]}
    issues = gh(f"repos/{a.repo}/issues?labels=verdict&state=all&per_page=100")
    cache: dict = {}
    vs, skipped = select(issues, debates, lambda login: account_created(login, cache))
    out = {"as_of": dt.date.today().isoformat(),
           "source": f"https://github.com/{a.repo}/issues?q=label%3Averdict",
           "rules": "One verdict per GitHub account per debate (the earliest), from accounts at least "
                    f"{MIN_AGE_DAYS} days old; issues closed as not planned are skipped.",
           "skipped": skipped, "verdicts": vs}
    (arena.ARENA_DIR / "verdicts.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"{len(vs)} verdicts counted from {len(issues)} issues; skipped {skipped}")
    return 0


def cmd_standings(a) -> int:
    st = arena.public_state()
    if not st:
        print("no arena")
        return 1
    names = {i["id"]: i["name"] for i in st["ideas"]}
    print(f"{st['stats']['verdicts']} verdicts on {st['stats']['judging']} finished debates\n\nIDEAS")
    for r in st["standings"]["ideas"]:
        print(f"  {r['rating']:6.0f} ± {2 * r['se']:4.0f}  {r['verdicts']:3d} verdicts  {names[r['id']]}")
    print("\nADVOCATES")
    for r in st["standings"]["advocates"]:
        print(f"  {r['rating']:6.0f} ± {2 * r['se']:4.0f}  {r['handle']}")
    return 0


def cmd_check(a) -> int:
    path = Path(a.file)
    r = json.loads(path.read_text(encoding="utf-8"))
    slot = f"{r.get('debate')}-{r.get('idea')}-{r.get('round')}"
    if not arena.SLOT.match(slot):
        print(f"REJECTED: debate, idea and round do not form a slot ({slot})")
        return 1
    problems = arena.validate(r, slot, arena.load())
    if path.name != f"{r['idea']}-{r['round']}.json" or path.parent.name != r["debate"]:
        problems.append(f"the file should be arena/rounds/{r['debate']}/{r['idea']}-{r['round']}.json")
    if not r.get("by"):
        problems.append("by (the advocate's handle) is missing")
    if problems:
        print("REJECTED:\n  " + "\n  ".join(problems))
        return 1
    res = arena.check_quotes(r)
    print(res["summary"])
    return 0 if res["ok"] else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("tally"); s.add_argument("--repo", default=REPO); s.set_defaults(f=cmd_tally)
    s = sub.add_parser("standings"); s.set_defaults(f=cmd_standings)
    s = sub.add_parser("check"); s.add_argument("file"); s.set_defaults(f=cmd_check)
    a = ap.parse_args()
    return a.f(a)


if __name__ == "__main__":
    sys.exit(main())
