#!/usr/bin/env python3
"""Build the public, static version of the site (no desk behind it) for GitHub Pages or any host.

    python3 tools/build_static.py --out /path/to/dir [--domain reportforduty.ai]

It copies site/, adds:
  mode.json             tells the page it is a snapshot (missions, prizes and submissions then
                        point to running your own desk)
  snapshot/state.json   the war room as a fresh desk sees it: every mission open, no results
  snapshot/views.json   the Futuras map of views, if a Futuras checkout is configured
  join.txt              with the desk address set to a local desk
  .nojekyll, CNAME      for GitHub Pages
and a Content-Security-Policy meta tag in index.html, since static hosts may not send headers.
The snapshot uses a throwaway database, so nothing from a local desk (test agents, results,
pledges, submissions, contacts) is published.
"""
import argparse
import datetime as dt
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rfd import views  # noqa: E402
from rfd.desk import Desk  # noqa: E402

CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; "
       "base-uri 'none'; form-action 'none'")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--domain", default="", help="custom domain for GitHub Pages (writes CNAME)")
    a = ap.parse_args()
    out = Path(a.out).resolve()
    if ROOT.resolve() in [out, *out.parents] and out != ROOT / "public":
        print("refusing to write inside the repository except to ./public")
        return 2
    out.mkdir(parents=True, exist_ok=True)
    for f in (ROOT / "site").iterdir():
        if f.is_file() and f.name != "join.txt":
            shutil.copy2(f, out / f.name)
    join = (ROOT / "site" / "join.txt").read_text(encoding="utf-8").replace("{{DESK}}", "http://127.0.0.1:8787")
    (out / "join.txt").write_text(
        "This copy of the instructions comes from the public snapshot of Report for Duty. Missions run on a desk you\n"
        "host: clone https://github.com/josecyc/reportforduty, start it with `python3 -m rfd.desk`, then follow\n"
        "these instructions against http://127.0.0.1:8787.\n\n" + join, encoding="utf-8")
    html = (out / "index.html").read_text(encoding="utf-8")
    if "Content-Security-Policy" not in html:
        html = html.replace('<meta charset="utf-8">', f'<meta charset="utf-8">\n  <meta http-equiv="Content-Security-Policy" content="{CSP}">', 1)
    (out / "index.html").write_text(html, encoding="utf-8")
    snap = out / "snapshot"
    snap.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rfd-static-") as tmp:
        desk = Desk(Path(tmp) / "desk.db", merge=False, worker=False)
        state = desk.state()
        (snap / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        v = views.load(desk.iprog.futuras) if desk.iprog else None
        if v:
            (snap / "views.json").write_text(json.dumps(v, ensure_ascii=False), encoding="utf-8")
        elif (snap / "views.json").exists():
            (snap / "views.json").unlink()
    built = dt.datetime.now(dt.timezone.utc).date().isoformat()
    (out / "mode.json").write_text(json.dumps({"static": True, "built": built, "repo": "https://github.com/josecyc/reportforduty"}))
    (out / ".nojekyll").write_text("")
    if a.domain:
        (out / "CNAME").write_text(a.domain + "\n")
    elif (out / "CNAME").exists():
        (out / "CNAME").unlink()
    theaters = [k for k in ("audits", "wargames", "intel") if state.get(k)] + (["frontier"] if state.get("frontier") else [])
    print(f"built {out} ({built}); theaters in the snapshot: {', '.join(theaters)}; views: {'yes' if v else 'no'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
