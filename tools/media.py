#!/usr/bin/env python3
"""Review submissions to the futures gallery. Runs locally against the desk's database; there is
no review endpoint over HTTP.

    python3 tools/media.py list              submissions awaiting review (with the private contact)
    python3 tools/media.py list --all
    python3 tools/media.py approve M-1a2b3c4d [--note "watched it"]
    python3 tools/media.py decline M-1a2b3c4d --note "uses a real person's likeness"

Before approving, open the link and check the work against the brief on the futures page: it
says it is fiction (and AI-generated, if it is), it is the submitter's own or they have permission,
it uses no real person's face or voice without consent, and the premise and assumptions match it.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rfd.desk import DATA_DIR, Desk  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(DATA_DIR / "desk.db"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("list"); s.add_argument("--all", action="store_true")
    s = sub.add_parser("approve"); s.add_argument("id"); s.add_argument("--note", default="")
    s = sub.add_parser("decline"); s.add_argument("id"); s.add_argument("--note", required=True)
    a = ap.parse_args()
    desk = Desk(Path(a.db), merge=False, worker=False)
    if a.cmd == "list":
        rows = desk.media.listing(include_all=a.all)
        for r in rows:
            print(f"{r['id']}  [{r['status']}]  {r['title']}  by {r['creator']}  ({r['medium']}, {r['tone']}"
                  f"{', AI-generated' if r['ai_generated'] else ''})")
            print(f"    link    : {r['url']}")
            print(f"    premise : {r['premise']}")
            print(f"    assumes : {r['assumes']}")
            print(f"    scenario: {r['scenario'] or '-'}")
            print(f"    contact : {r['contact']}   (private)")
        print(f"{len(rows)} submission{'s' if len(rows) != 1 else ''}{'' if a.all else ' awaiting review'}")
        return 0
    ok, msg = desk.media.review(a.id, a.cmd == "approve", a.note)
    print(f"{a.id}: {msg}")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
