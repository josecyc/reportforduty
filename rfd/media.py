"""Submissions to the futures gallery: works (videos, stories, art) that show how the future with
advanced AI could go. Anyone can submit; a person reviews every submission before it appears, so
free text from strangers never reaches the site unreviewed. The contact address is kept for the
reviewer and never served.

    pending -> approved | declined        (tools/media.py)
"""
from __future__ import annotations

import json
import re
import secrets
import time
from pathlib import Path

from .registry import ROOT

SCHEMA = """
CREATE TABLE IF NOT EXISTS media(
  id TEXT PRIMARY KEY, created REAL NOT NULL, title TEXT NOT NULL, creator TEXT NOT NULL, url TEXT NOT NULL,
  medium TEXT NOT NULL, tone TEXT NOT NULL, premise TEXT NOT NULL, assumes TEXT NOT NULL, scenario TEXT,
  ai_generated INTEGER NOT NULL, contact TEXT NOT NULL, status TEXT NOT NULL, reviewed REAL, note TEXT);
"""
MEDIA = ("video", "short-film", "film", "story", "novel", "art", "music", "game", "essay", "other")
TONES = ("hopeful", "cautionary", "mixed")
PLAIN = re.compile(r"^[^\x00-\x1f\x7f<>]*$")
FUTURES = ROOT / "site" / "futures.json"


def scenario_ids() -> set[str]:
    try:
        return {s["id"] for s in json.loads(FUTURES.read_text(encoding="utf-8")).get("scenarios", [])}
    except (OSError, ValueError, KeyError, TypeError):
        return set()


class Media:
    def __init__(self, desk):
        self.desk = desk
        desk.db.executescript(SCHEMA)

    def validate(self, b: dict) -> tuple[list[str], dict]:
        errs, out = [], {}

        def text(k, lo, hi, required=True):
            v = b.get(k, "")
            v = v.strip() if isinstance(v, str) else ""
            if not v and not required:
                return ""
            if not (lo <= len(v) <= hi) or not PLAIN.match(v):
                errs.append(f"{k}: {lo} to {hi} characters, one line, no angle brackets")
            return v

        out["title"] = text("title", 2, 120)
        out["creator"] = text("creator", 2, 80)
        out["premise"] = text("premise", 20, 300)
        out["assumes"] = text("assumes", 10, 300)
        out["contact"] = text("contact", 3, 200)
        url = text("url", 12, 300)
        if url and not url.startswith("https://"):
            errs.append("url: a public https link to the work")
        out["url"] = url
        out["medium"] = b.get("medium") if b.get("medium") in MEDIA else errs.append("medium: one of " + ", ".join(MEDIA))
        out["tone"] = b.get("tone") if b.get("tone") in TONES else errs.append("tone: hopeful, cautionary or mixed")
        sc = b.get("scenario") or ""
        if sc and sc not in scenario_ids():
            errs.append("scenario: one of the twelve scenarios on the futures page, or empty")
        out["scenario"] = sc or None
        out["ai_generated"] = bool(b.get("ai_generated"))
        for k, why in (("rights", "confirm the work is yours, or you have permission from whoever holds the rights"),
                       ("labelled", "confirm the work says it is fiction, and says so if it is AI-generated"),
                       ("likeness", "confirm it uses no real person's face or voice without their consent")):
            if b.get(k) is not True:
                errs.append(f"{k}: {why}")
        return errs, out

    def submit(self, body: bytes) -> tuple[int, dict]:
        try:
            b = json.loads(body.decode("utf-8"))
            if not isinstance(b, dict):
                raise ValueError
        except (UnicodeDecodeError, ValueError):
            return 400, {"error": "send the submission as a JSON object"}
        errs, m = self.validate(b)
        if errs:
            return 422, {"error": "the submission was not accepted", "reasons": errs}
        mid = "M-" + secrets.token_hex(4)
        with self.desk.lock:
            self.desk.db.execute(
                "INSERT INTO media(id,created,title,creator,url,medium,tone,premise,assumes,scenario,ai_generated,contact,status)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'pending')",
                (mid, time.time(), m["title"], m["creator"], m["url"], m["medium"], m["tone"], m["premise"], m["assumes"],
                 m["scenario"], 1 if m["ai_generated"] else 0, m["contact"]))
        return 202, {"submission": mid, "status": "pending", "next": "A person reviews every submission before it appears in the gallery."}

    def review(self, mid: str, approve: bool, note: str = "") -> tuple[bool, str]:
        with self.desk.lock:
            row = self.desk.db.execute("SELECT * FROM media WHERE id=?", (mid,)).fetchone()
            if not row:
                return False, "no such submission"
            if row["status"] != "pending":
                return False, f"submission is {row['status']}, not pending"
            self.desk.db.execute("UPDATE media SET status=?, reviewed=?, note=? WHERE id=?",
                                 ("approved" if approve else "declined", time.time(), note, mid))
            if approve:
                self.desk.event("media_added", None, None, title=row["title"], creator=row["creator"], tone=row["tone"], media=mid)
        return True, "approved" if approve else "declined"

    def state(self) -> dict:
        rows = self.desk.db.execute("SELECT * FROM media WHERE status='approved' ORDER BY reviewed DESC").fetchall()
        works = [{"id": r["id"], "title": r["title"], "creator": r["creator"], "url": r["url"], "medium": r["medium"],
                  "tone": r["tone"], "premise": r["premise"], "assumes": r["assumes"], "scenario": r["scenario"] or "",
                  "ai_generated": bool(r["ai_generated"]), "added": r["reviewed"], "submitted": True} for r in rows]
        pending = self.desk.db.execute("SELECT COUNT(*) FROM media WHERE status='pending'").fetchone()[0]
        return {"works": works, "pending_review": pending}

    def listing(self, include_all: bool = False) -> list:
        q = "SELECT * FROM media" + ("" if include_all else " WHERE status='pending'") + " ORDER BY created"
        return [dict(r) for r in self.desk.db.execute(q)]
