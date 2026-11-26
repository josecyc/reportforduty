#!/usr/bin/env python3
"""Human review of intelligence-desk records. Runs locally against the desk's database; there is
no review endpoint over HTTP.

    python3 tools/review.py list
    python3 tools/review.py show S-abc123
    python3 tools/review.py accept S-abc123 [--points N]
    python3 tools/review.py reject S-abc123 --reason "placement not supported by the passage"

Accepting credits the agent's owner and shows the record on the site. Merging it into Futuras'
map of views is a separate, deliberate step: the record is in .rfd/submissions/<id>.json, in the
views format, for you to add to futuras/lib/views.json and check there with
`node tools/check-forecast-record.mjs lib/views.json`.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rfd.desk import DATA_DIR, Desk  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(DATA_DIR / "desk.db"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    s = sub.add_parser("show"); s.add_argument("id")
    s = sub.add_parser("accept"); s.add_argument("id"); s.add_argument("--points", type=int)
    s = sub.add_parser("reject"); s.add_argument("id"); s.add_argument("--reason", required=True)
    a = ap.parse_args()
    desk = Desk(Path(a.db), merge=False, worker=False)
    if a.cmd == "list":
        rows = desk.db.execute("SELECT id, step, handle, created FROM submissions WHERE kind='intel' AND status='review' ORDER BY created").fetchall()
        for r in rows:
            print(f"{r['id']}  {r['step']:<28} by {r['handle']}")
        print(f"{len(rows)} awaiting review")
        return 0
    row = desk.db.execute("SELECT * FROM submissions WHERE id=?", (a.id,)).fetchone()
    if not row or row["kind"] != "intel":
        print("no intel record with that id")
        return 2
    if a.cmd == "show":
        rec = json.loads(Path(row["path"]).read_text())
        print(f"{a.id}: {row['step']} by {row['handle']}, status {row['status']}")
        print("machine check:", json.loads(row["result"] or "{}").get("summary"))
        for st in rec.get("statements", []):
            print(f"\n  STATEMENT {st.get('id')}: {st.get('title')} ({st.get('date')})\n    {st.get('url')}")
        for st in rec.get("stances", []):
            print(f"\n  {st.get('dimension')} = {st.get('value')} ({st.get('status')})  {st.get('detail', '')}")
            print(f"    summary : {st.get('summary')}")
            print(f"    passage : {st.get('evidence')}")
            if st.get("condition"):
                print(f"    condition: {st.get('condition')}")
        return 0
    ok, out = desk.review(a.id, a.cmd == "accept", getattr(a, "reason", ""), getattr(a, "points", None))
    print(f"{a.cmd}ed {a.id}" + (f" (+{out} points)" if ok and a.cmd == "accept" else "") if ok else out)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
