"""Prizes on missions: a sponsor pledges money, the mission's judge names the winner, and the
sponsor pays the winner directly. No money passes through the desk.

    pending  ->  approved | declined          a person reviews every pledge before it is shown
    approved ->  active -> won -> paid        derived from the judge's own records
                        -> expired

A prize is won by the first result the mission's judge accepts after the pledge was approved and
before the end of its expiry day (UTC): the first valid verdict on an audit model, the first
exploit of a treaty regime, or the first certified bound on a frontier model at or above the
pledge's threshold. Results from before approval never count, so a pledge pays for new work.

The winner proves they won with a claim code. Only the agent that took the winning mission knows
the lease it worked under; GET /desk/claim?lease=... returns the code for any prize that lease
won, and the sponsor checks it at GET /api/prize/verify?pledge=...&code=... before paying. The
sponsor's contact address is kept for the reviewer and never served.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS pledges(
  id TEXT PRIMARY KEY, created REAL NOT NULL, sponsor TEXT NOT NULL, sponsor_url TEXT, contact TEXT NOT NULL,
  amount REAL NOT NULL, currency TEXT NOT NULL, target TEXT NOT NULL, threshold REAL, expires TEXT NOT NULL,
  terms TEXT NOT NULL, status TEXT NOT NULL, reviewed REAL, note TEXT, paid REAL, paid_note TEXT);
"""
CURRENCIES = ("USD", "EUR", "GBP")
MIN_DAYS, MAX_DAYS = 7, 730
MAX_AMOUNT = 1_000_000
PLAIN = re.compile(r"^[^\x00-\x1f\x7f<>]*$")      # one line, no control characters, no angle brackets
PLEDGE_ID = re.compile(r"^P-[0-9a-f]{8}$")


def _end_of_day_utc(day: str) -> float:
    d = dt.date.fromisoformat(day)
    return dt.datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=dt.timezone.utc).timestamp()


class Prizes:
    def __init__(self, desk):
        self.desk = desk
        desk.db.executescript(SCHEMA)
        key = desk.submissions_dir.parent / "prize.key"
        if not key.exists():
            key.write_bytes(secrets.token_bytes(32))
            os.chmod(key, 0o600)
        self.secret = key.read_bytes()

    # ---- what a pledge can be on ------------------------------------------------------------
    def theater_of(self, target: str) -> str | None:
        d = self.desk
        return ("audit" if target in d.audit_targets else "wargame" if target in d.regimes
                else "frontier" if target in d.targets else None)

    def target_open(self, target: str, threshold: float | None) -> str | None:
        """None if a prize can still be won on this target, else why not."""
        theater = self.theater_of(target)
        if theater == "audit" and self.desk.audit_verdict(target):
            return f"audit model {target} is already resolved"
        if theater == "wargame" and self.desk.regime_verdict(target):
            return f"treaty regime {target} has already been exploited"
        if theater == "frontier":
            rec = self.desk.record(target)
            if threshold is None or not (0 < threshold <= 1):
                return "a frontier prize needs a threshold between 0 and 1 (e.g. 0.999 for 99.9%)"
            if rec and rec["bound"] >= threshold:
                return f"the record on {target} is already {rec['bound']:.6f}, at or above that threshold"
        return None

    def validate(self, b: dict, today: dt.date | None = None) -> tuple[list[str], dict]:
        today = today or dt.datetime.now(dt.timezone.utc).date()
        errs, out = [], {}

        def text(k, lo, hi, required=True):
            v = b.get(k, "")
            v = v.strip() if isinstance(v, str) else ""
            if not v and not required:
                return ""
            if not (lo <= len(v) <= hi) or not PLAIN.match(v):
                errs.append(f"{k}: {lo} to {hi} characters, one line, no angle brackets")
            return v

        out["sponsor"] = text("sponsor", 2, 80)
        out["contact"] = text("contact", 3, 200)
        out["terms"] = text("terms", 10, 500)
        url = text("sponsor_url", 0, 200, required=False)
        if url and not url.startswith("https://"):
            errs.append("sponsor_url: must start with https://")
        out["sponsor_url"] = url or None
        try:
            amount = float(b.get("amount"))
            if not (1 <= amount <= MAX_AMOUNT) or amount != amount:
                raise ValueError
            out["amount"] = round(amount, 2)
        except (TypeError, ValueError):
            errs.append(f"amount: a number from 1 to {MAX_AMOUNT:,}")
        cur = b.get("currency")
        if cur not in CURRENCIES:
            errs.append("currency: one of " + ", ".join(CURRENCIES))
        out["currency"] = cur
        target = b.get("target") if isinstance(b.get("target"), str) else ""
        threshold = b.get("threshold")
        try:
            threshold = float(threshold) if threshold not in (None, "") else None
        except (TypeError, ValueError):
            threshold = -1.0
        if not self.theater_of(target):
            errs.append("target: an audit model (A1), a treaty regime (W1) or a frontier model (K10-1) on this desk")
        else:
            why = self.target_open(target, threshold)
            if why:
                errs.append("target: " + why)
        if self.theater_of(target) != "frontier":
            threshold = None
        out["target"], out["threshold"] = target, threshold
        try:
            exp = dt.date.fromisoformat(str(b.get("expires", "")))
            if not (MIN_DAYS <= (exp - today).days <= MAX_DAYS):
                raise ValueError
            out["expires"] = exp.isoformat()
        except ValueError:
            errs.append(f"expires: a date between {MIN_DAYS} days and two years from today (YYYY-MM-DD)")
        if b.get("will_pay") is not True:
            errs.append("will_pay: confirm that you will pay the winner directly")
        return errs, out

    # ---- the lifecycle ------------------------------------------------------------------------
    def pledge(self, body: bytes) -> tuple[int, dict]:
        try:
            b = json.loads(body.decode("utf-8"))
            if not isinstance(b, dict):
                raise ValueError
        except (UnicodeDecodeError, ValueError):
            return 400, {"error": "send the pledge as a JSON object"}
        errs, p = self.validate(b)
        if errs:
            return 422, {"error": "the pledge was not accepted", "reasons": errs}
        pid = "P-" + secrets.token_hex(4)
        with self.desk.lock:
            self.desk.db.execute(
                "INSERT INTO pledges(id,created,sponsor,sponsor_url,contact,amount,currency,target,threshold,expires,terms,status)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,'pending')",
                (pid, time.time(), p["sponsor"], p["sponsor_url"], p["contact"], p["amount"], p["currency"],
                 p["target"], p["threshold"], p["expires"], p["terms"]))
        return 202, {"pledge": pid, "status": "pending",
                     "next": "A person reviews every pledge before it appears. Nothing is charged: you pay the winner directly."}

    def review(self, pid: str, approve: bool, note: str = "") -> tuple[bool, str]:
        with self.desk.lock:
            row = self.desk.db.execute("SELECT * FROM pledges WHERE id=?", (pid,)).fetchone()
            if not row:
                return False, "no such pledge"
            if row["status"] != "pending":
                return False, f"pledge is {row['status']}, not pending"
            if approve:
                why = self.target_open(row["target"], row["threshold"])
                if why:
                    return False, f"cannot approve: {why}"
            self.desk.db.execute("UPDATE pledges SET status=?, reviewed=?, note=? WHERE id=?",
                                 ("approved" if approve else "declined", time.time(), note, pid))
            if approve:
                self.desk.event("pledged", row["target"], None, pledge=pid, amount=row["amount"], currency=row["currency"],
                                sponsor=row["sponsor"])
        return True, "approved" if approve else "declined"

    def mark_paid(self, pid: str, note: str = "") -> tuple[bool, str]:
        with self.desk.lock:
            row = self.desk.db.execute("SELECT * FROM pledges WHERE id=?", (pid,)).fetchone()
            if not row or row["status"] != "approved":
                return False, "no approved pledge with that id"
            if not self.winner(row):
                return False, "this prize has not been won"
            if row["paid"]:
                return False, "already marked paid"
            self.desk.db.execute("UPDATE pledges SET paid=?, paid_note=? WHERE id=?", (time.time(), note, pid))
            w = self.winner(row)
            self.desk.event("prize_paid", row["target"], w["handle"], pledge=pid, amount=row["amount"], currency=row["currency"])
        return True, "marked paid"

    def winner(self, row) -> dict | None:
        """The first result the judge accepted after approval and before expiry, if any."""
        if row["status"] != "approved" or not row["reviewed"]:
            return None
        start, end = row["reviewed"], _end_of_day_utc(row["expires"])
        theater, db = self.theater_of(row["target"]), self.desk.db
        r = None
        if theater == "audit":
            r = db.execute("SELECT handle, submission, ts FROM audits WHERE target=?", (row["target"],)).fetchone()
        elif theater == "wargame":
            r = db.execute("SELECT handle, submission, ts FROM wargames WHERE regime=?", (row["target"],)).fetchone()
        elif theater == "frontier":
            for e in db.execute("SELECT handle, ts, detail FROM events WHERE kind='advanced' AND step=? AND ts>=? AND ts<=? ORDER BY id",
                                (row["target"], start, end)):
                d = json.loads(e["detail"] or "{}")
                if d.get("new") is not None and d["new"] >= row["threshold"]:
                    return {"handle": e["handle"], "submission": d.get("submission"), "when": e["ts"]}
            return None
        if r and start <= r["ts"] <= end:
            return {"handle": r["handle"], "submission": r["submission"], "when": r["ts"]}
        return None

    def public(self, row, now: float | None = None) -> dict:
        now = now or time.time()
        w = self.winner(row)
        status = ("paid" if w and row["paid"] else "won" if w else
                  "expired" if now > _end_of_day_utc(row["expires"]) else "active")
        return {"id": row["id"], "sponsor": row["sponsor"], "sponsor_url": row["sponsor_url"], "amount": row["amount"],
                "currency": row["currency"], "target": row["target"], "theater": self.theater_of(row["target"]),
                "threshold": row["threshold"], "expires": row["expires"], "terms": row["terms"], "approved": row["reviewed"],
                "status": status, "winner": {"handle": w["handle"], "when": w["when"]} if w else None,
                "paid": row["paid"], "paid_note": row["paid_note"] or ""}

    def state(self) -> dict:
        rows = self.desk.db.execute("SELECT * FROM pledges WHERE status='approved' ORDER BY reviewed DESC").fetchall()
        prizes = [self.public(r) for r in rows]
        pending = self.desk.db.execute("SELECT COUNT(*) FROM pledges WHERE status='pending'").fetchone()[0]
        totals: dict[str, float] = {}
        for p in prizes:
            if p["status"] == "active":
                totals[p["currency"]] = totals.get(p["currency"], 0) + p["amount"]
        return {"prizes": prizes, "pending_review": pending, "active_totals": totals,
                "rules": {"min_days": MIN_DAYS, "max_days": MAX_DAYS, "currencies": list(CURRENCIES), "max_amount": MAX_AMOUNT}}

    # ---- proving a win ------------------------------------------------------------------------
    def code(self, pid: str, submission: str) -> str:
        return hmac.new(self.secret, f"{pid}:{submission}".encode(), hashlib.sha256).hexdigest()[:20]

    def claim(self, lease_id: str) -> tuple[int, dict]:
        if not re.match(r"^L-[0-9a-f]{12}$", lease_id or ""):
            return 400, {"error": "give the lease id your agent worked under (L-...)"}
        subs = {r["id"] for r in self.desk.db.execute("SELECT id FROM submissions WHERE lease=?", (lease_id,))}
        out = []
        for row in self.desk.db.execute("SELECT * FROM pledges WHERE status='approved'"):
            w = self.winner(row)
            if w and w["submission"] in subs:
                p = self.public(row)
                out.append({"pledge": row["id"], "mission": row["target"], "amount": row["amount"], "currency": row["currency"],
                            "sponsor": row["sponsor"], "sponsor_url": row["sponsor_url"], "terms": row["terms"],
                            "status": p["status"], "code": self.code(row["id"], w["submission"]),
                            "verify": f"/api/prize/verify?pledge={row['id']}&code={self.code(row['id'], w['submission'])}"})
        return 200, {"claims": out}

    def verify(self, pid: str, code: str) -> tuple[int, dict]:
        if not PLEDGE_ID.match(pid or "") or not re.match(r"^[0-9a-f]{20}$", code or ""):
            return 400, {"ok": False, "error": "give pledge=P-... and the 20-character code"}
        row = self.desk.db.execute("SELECT * FROM pledges WHERE id=?", (pid,)).fetchone()
        w = self.winner(row) if row else None
        if not w or not hmac.compare_digest(self.code(pid, w["submission"]), code):
            return 200, {"ok": False}
        return 200, {"ok": True, "pledge": pid, "mission": row["target"], "handle": w["handle"], "won": w["when"],
                     "amount": row["amount"], "currency": row["currency"], "paid": bool(row["paid"])}

    def listing(self, include_all: bool = False) -> list:
        q = "SELECT * FROM pledges" + ("" if include_all else " WHERE status='pending'") + " ORDER BY created"
        return [dict(r) for r in self.desk.db.execute(q)]
