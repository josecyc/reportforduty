#!/usr/bin/env python3
"""Review prize pledges and record payouts. Runs locally against the desk's database; there is no
review endpoint over HTTP.

    python3 tools/prizes.py list            pledges awaiting review (with the sponsor's private contact)
    python3 tools/prizes.py list --all      every pledge
    python3 tools/prizes.py approve P-1a2b3c4d [--note "checked the sponsor"]
    python3 tools/prizes.py decline P-1a2b3c4d --note "could not confirm the sponsor"
    python3 tools/prizes.py paid P-1a2b3c4d --note "sponsor confirmed payment on 2027-01-12"

Before approving, confirm the sponsor is who they say they are, using the contact they gave.
Approval shows the pledge on the site and starts the clock: only results after this moment count.
Mark a prize paid only when the sponsor confirms payment; the site then shows it as paid.
"""
import argparse
import datetime as dt
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
    s = sub.add_parser("paid"); s.add_argument("id"); s.add_argument("--note", required=True)
    a = ap.parse_args()
    desk = Desk(Path(a.db), merge=False, worker=False)
    pz = desk.prizes
    if a.cmd == "list":
        rows = pz.listing(include_all=a.all)
        for r in rows:
            when = dt.datetime.fromtimestamp(r["created"]).strftime("%Y-%m-%d %H:%M")
            thr = f" at or above {r['threshold']}" if r["threshold"] is not None else ""
            status = r["status"]
            if status == "approved":
                status = pz.public(desk.db.execute("SELECT * FROM pledges WHERE id=?", (r["id"],)).fetchone())["status"]
            print(f"{r['id']}  [{status}]  {r['amount']:,.2f} {r['currency']} on {r['target']}{thr}, until {r['expires']}  ({when})")
            print(f"    sponsor : {r['sponsor']}  {r['sponsor_url'] or ''}")
            print(f"    contact : {r['contact']}   (private)")
            print(f"    terms   : {r['terms']}")
        print(f"{len(rows)} pledge{'s' if len(rows) != 1 else ''}{'' if a.all else ' awaiting review'}")
        return 0
    if a.cmd in ("approve", "decline"):
        ok, msg = pz.review(a.id, a.cmd == "approve", a.note)
    else:
        ok, msg = pz.mark_paid(a.id, a.note)
    print(f"{a.id}: {msg}")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
