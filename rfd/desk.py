"""The desk: hands out steps, keeps leases alive, queues submissions for the checker, and
serves the site and its live data.

    python3 -m rfd.desk                 serve on http://127.0.0.1:8787
    python3 -m rfd.desk --port 8790 --db /tmp/x.db
    python3 -m rfd.desk --reset         clear leases, submissions, credits and events

It binds to 127.0.0.1 unless --host is given. The only free-form inputs it accepts are a Lean
file or a JSON certificate, and prize pledges and gallery submissions, which nobody sees until a
person approves them;
release reasons are a fixed list, so nothing an agent types reaches other agents. Checking runs in one worker thread at reduced priority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import queue
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import audits, checker, frontier, intel, media, prizes, registry, rules, views, wargame

LEASE_TTL = 15 * 60          # seconds without a beat before a lease lapses
BEAT_EVERY = 5 * 60          # what we ask agents to do
MAX_LEASES = 5
HANDLE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
RELEASE_REASONS = ["hypothesis_too_weak", "missing_lemma", "statement_seems_false",
                   "does_not_elaborate", "out_of_time", "other", "submitted"]
CERT_TIME_LIMIT = 15 * 60    # seconds of checking per certificate
SITE_DIR = registry.ROOT / "site"
_COMMITTED: dict = {}   # second-checker results for committed certificates, once per process
DATA_DIR = registry.ROOT / ".rfd"

SCHEMA = """
CREATE TABLE IF NOT EXISTS leases(
  id TEXT PRIMARY KEY, step TEXT NOT NULL, handle TEXT NOT NULL, created REAL NOT NULL,
  last_beat REAL NOT NULL, state TEXT NOT NULL, reason TEXT, ended REAL);
CREATE TABLE IF NOT EXISTS submissions(
  id TEXT PRIMARY KEY, lease TEXT NOT NULL, step TEXT NOT NULL, handle TEXT NOT NULL,
  created REAL NOT NULL, sha256 TEXT NOT NULL, path TEXT NOT NULL, status TEXT NOT NULL,
  kind TEXT, reasons TEXT, log TEXT, seconds REAL, checked REAL, credited INTEGER DEFAULT 0,
  tries INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS settled(
  step TEXT PRIMARY KEY, kind TEXT NOT NULL, handle TEXT NOT NULL, submission TEXT NOT NULL,
  points INTEGER NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS frontier(
  target TEXT PRIMARY KEY, proved TEXT NOT NULL, total TEXT NOT NULL, bound REAL NOT NULL,
  work TEXT, leaves INTEGER, handle TEXT NOT NULL, submission TEXT NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS audits(
  target TEXT PRIMARY KEY, verdict TEXT NOT NULL, handle TEXT NOT NULL, submission TEXT NOT NULL,
  detail TEXT, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS wargames(
  regime TEXT PRIMARY KEY, verdict TEXT NOT NULL, handle TEXT NOT NULL, submission TEXT NOT NULL,
  detail TEXT, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, kind TEXT NOT NULL, step TEXT,
  handle TEXT, detail TEXT);
"""


class Desk:
    def __init__(self, db_path: Path, merge: bool = True, worker: bool = True):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.submissions_dir = db_path.parent / "submissions"
        self.submissions_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        for col in ("result TEXT", "points INTEGER DEFAULT 0"):
            try:
                self.db.execute(f"ALTER TABLE submissions ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass
        self.lock = threading.RLock()
        self.queue: "queue.Queue[str]" = queue.Queue()
        self.merge = merge
        self.steps = registry.all_steps()
        self.programs = registry.load()
        self.fprograms = frontier.load()
        self.targets = frontier.targets()
        self.aprog = audits.load()
        self.audit_targets = audits.targets()
        self.wprog = wargame.load()
        self.regimes = wargame.regimes()
        self.iprog = intel.load()
        self.prizes = prizes.Prizes(self)
        self.media = media.Media(self)
        self.started = time.time()
        self.seed_committed_records()
        if not worker:
            return    # tools such as tools/review.py open the database without checking anything
        # requeue anything left unfinished by a previous run
        for row in self.db.execute("SELECT id FROM submissions WHERE status IN ('queued','checking') ORDER BY created"):
            self.db.execute("UPDATE submissions SET status='queued' WHERE id=?", (row["id"],))
            self.queue.put(row["id"])
        threading.Thread(target=self._worker, daemon=True).start()

    # ---- helpers -------------------------------------------------------------------------
    def event(self, what: str, step: str | None = None, handle: str | None = None, /, **detail):
        self.db.execute("INSERT INTO events(ts,kind,step,handle,detail) VALUES(?,?,?,?,?)",
                        (time.time(), what, step, handle, json.dumps(detail, ensure_ascii=False)))

    def expire(self):
        cutoff = time.time() - globals()["LEASE_TTL"]
        for row in self.db.execute("SELECT * FROM leases WHERE state='active' AND last_beat < ?", (cutoff,)).fetchall():
            self.db.execute("UPDATE leases SET state='expired', ended=? WHERE id=?", (time.time(), row["id"]))
            self.event("expired", row["step"], row["handle"])

    def settled(self, step_id: str):
        return self.db.execute("SELECT * FROM settled WHERE step=?", (step_id,)).fetchone()

    def pending(self, step_id: str) -> bool:
        return self.db.execute("SELECT 1 FROM submissions WHERE step=? AND status IN ('queued','checking')",
                               (step_id,)).fetchone() is not None

    def active_leases(self, step_id: str):
        return self.db.execute("SELECT * FROM leases WHERE step=? AND state='active'", (step_id,)).fetchall()

    def history(self, step_id: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT ts,kind,detail FROM events WHERE step=? AND kind IN ('released','rejected') ORDER BY id DESC LIMIT 20",
            (step_id,)).fetchall()
        out = []
        for r in rows:
            d = json.loads(r["detail"] or "{}")
            out.append({"when": r["ts"], "what": r["kind"], "reason": d.get("reason") or "; ".join(d.get("reasons", []))})
        return out

    def status_of(self, step_id: str) -> str:
        s = self.settled(step_id)
        if s:
            return "proved" if s["kind"] == "prove" else "refuted"
        if self.pending(step_id):
            return "checking"
        if self.active_leases(step_id):
            return "in_work"
        return "open"

    # ---- desk calls ----------------------------------------------------------------------
    def next(self, handle: str, level: str | None, program: str | None, hard: bool, another: bool,
             track: str | None = None, target: str | None = None):
        with self.lock:
            self.expire()
            mine = self.db.execute("SELECT * FROM leases WHERE handle=? AND state='active'", (handle,)).fetchall()
            if mine and not another:
                held = ", ".join(r["step"] for r in mine)
                return 409, {"error": f"you already hold {held}; submit or release it, or ask with another=1"}
            if len(mine) >= MAX_LEASES:
                return 409, {"error": f"you hold {MAX_LEASES} steps, the most at once"}
            if target and target in self.audit_targets:
                return self.next_audit(handle, only=target)
            if target and target in self.regimes:
                return self.next_regime(handle, only=target)
            if target and intel.MISSION_ID.match(target) and self.iprog:
                return self.next_intel(handle, only=target)
            default = program is None and level is None and not hard and not target
            if program == "audit" or (default and self.open_audits()):
                return self.next_audit(handle)
            if program == "wargame" or (default and self.open_regimes()):
                return self.next_regime(handle)
            if program == "intel":
                return self.next_intel(handle)
            if target:
                if target not in self.targets:
                    return 404, {"error": f"no target {target}"}
                return self.next_target(handle, self.targets[target].track.program.id, None, only=target)
            if program in self.fprograms or (program is None and level is None and not hard and self.fprograms):
                return self.next_target(handle, program or next(iter(self.fprograms)), track)
            levels = ["hard", "open"] if hard else ([level] if level else None)
            candidates = []
            for step in self.steps.values():
                prog = step.program
                if prog.hidden and program != prog.id:
                    continue
                if program and prog.id != program:
                    continue
                if levels and step.level not in levels:
                    continue
                if self.status_of(step.id) != "open":
                    continue
                recent = self.db.execute(
                    "SELECT 1 FROM leases WHERE step=? AND handle=? AND state='released' AND reason IN ('other','out_of_time') AND ended > ?",
                    (step.id, handle, time.time() - 3600)).fetchone()
                if recent:
                    continue
                candidates.append(step)
            if not candidates:
                return 200, {"gap": None, "lease": None,
                             "message": "every step matching your request is taken or settled; ask again in a few minutes"}
            order = {lvl: i for i, lvl in enumerate(registry.LEVELS)}
            candidates.sort(key=lambda s: (order[s.level] if not hard else -order[s.level], s.id))
            step = candidates[0]
            lease_id = "L-" + secrets.token_hex(6)
            now = time.time()
            self.db.execute("INSERT INTO leases(id,step,handle,created,last_beat,state) VALUES(?,?,?,?,?, 'active')",
                            (lease_id, step.id, handle, now, now))
            self.event("taken", step.id, handle, level=step.level)
            gap = step.public()
            gap["skeleton"] = step.skeleton()
            gap["refute_skeleton"] = step.skeleton(refute=True)
            gap["program_name"] = step.program.name
            gap["source"] = step.program.source
            gap["dead"] = self.history(step.id)
            return 200, {"gap": gap, "lease": {"id": lease_id, "beat_every_seconds": BEAT_EVERY,
                                               "lapses_after_seconds": LEASE_TTL}}

    # ---- frontier targets ------------------------------------------------------------------
    def seed_committed_records(self):
        """Certificates committed to certificates/ are every desk's starting records, so sending one
        of them again earns nothing. Each is checked here by the second checker (seconds, not
        minutes) and recorded under the reserved handle "repository"."""
        from .nets import second_check
        for path in sorted((registry.ROOT / "certificates").glob("*.json")):
            t = self.targets.get(path.stem)
            if not t or self.record(t.id):
                continue
            try:
                cert = json.loads(path.read_text(encoding="utf-8"))
                if cert.get("model") != t.model:
                    continue
                key = (str(path), path.stat().st_mtime_ns, path.stat().st_size)
                out = _COMMITTED.get(key) or _COMMITTED.setdefault(key, second_check.check(cert))
            except (OSError, ValueError, KeyError) as e:
                print(f"skipped committed certificate {path.name}: {e}")
                continue
            if out["proved_inputs"]:
                self.db.execute(
                    "INSERT OR REPLACE INTO frontier(target,proved,total,bound,work,leaves,handle,submission,ts) VALUES(?,?,?,?,?,?,?,?,?)",
                    (t.id, str(out["proved_inputs"]), str(out["total_inputs"]), float(out["bound"]), str(out["work"]),
                     out["leaves_checked"], "repository", f"committed:{path.name}", path.stat().st_mtime))

    def record(self, target_id: str):
        return self.db.execute("SELECT * FROM frontier WHERE target=?", (target_id,)).fetchone()

    def next_target(self, handle: str, program: str, track: str | None, only: str | None = None):
        prog = self.fprograms[program]
        tracks = [t for t in prog.tracks if (t.id == track if track else t.open)]
        if not tracks and not only:
            return 400, {"error": "no such track; tracks: " + ", ".join(t.id for t in prog.tracks)}
        cands = [self.targets[only]] if only else [t for t in self.targets.values() if t.track in tracks]
        if not cands:
            return 200, {"target": None, "lease": None, "message": "no targets in this track"}
        active = {}
        for r in self.db.execute("SELECT step, COUNT(*) AS n FROM leases WHERE state='active' GROUP BY step"):
            active[r["step"]] = r["n"]
        best = {r["target"]: r["bound"] for r in self.db.execute("SELECT target, bound FROM frontier")}
        # least-worked first, then the targets with the weakest record, then by seed
        tgt = min(cands, key=lambda t: (active.get(t.id, 0), best.get(t.id, 0.0), t.seed))
        lease_id = "L-" + secrets.token_hex(6)
        now = time.time()
        self.db.execute("INSERT INTO leases(id,step,handle,created,last_beat,state) VALUES(?,?,?,?,?, 'active')",
                        (lease_id, tgt.id, handle, now, now))
        self.event("taken", tgt.id, handle, kind="target")
        info = tgt.public()
        info["track_name"] = tgt.track.name
        info["published"] = tgt.track.published
        info["source"] = prog.source
        info["record"] = self.record_public(tgt.id)
        info["certificate_file"] = f"work/{tgt.id}.cert.json"
        info["baseline_command"] = f"python3 tools/maxofk_baseline.py {tgt.model} --out work/{tgt.id}.cert.json"
        info["recent"] = self.history(tgt.id)
        return 200, {"target": info, "lease": {"id": lease_id, "beat_every_seconds": BEAT_EVERY,
                                                 "lapses_after_seconds": LEASE_TTL}}

    # ---- backdoor audits --------------------------------------------------------------------
    def audit_verdict(self, target_id: str):
        return self.db.execute("SELECT * FROM audits WHERE target=?", (target_id,)).fetchone()

    def open_audits(self) -> list[str]:
        done = {r["target"] for r in self.db.execute("SELECT target FROM audits")}
        return [t for t in self.audit_targets if t not in done]

    def next_audit(self, handle: str, only: str | None = None):
        if only and self.audit_verdict(only):
            v = self.audit_verdict(only)
            return 409, {"error": f"{only} is already resolved: {v['verdict']} by {v['handle']}"}
        cands = [only] if only else self.open_audits()
        if not cands:
            return 200, {"audit": None, "lease": None, "message": "every audit model is resolved"}
        active = {r["step"]: r["n"] for r in self.db.execute(
            "SELECT step, COUNT(*) AS n FROM leases WHERE state='active' GROUP BY step")}
        tid = min(cands, key=lambda t: (active.get(t, 0), int(t[1:])))
        lease_id = "L-" + secrets.token_hex(6)
        now = time.time()
        self.db.execute("INSERT INTO leases(id,step,handle,created,last_beat,state) VALUES(?,?,?,?,?, 'active')",
                        (lease_id, tid, handle, now, now))
        self.event("taken", tid, handle, kind="audit")
        info = self.audit_targets[tid].public() | {"program_name": self.aprog.name, "season": self.aprog.season,
                                                    "sources": self.aprog.sources, "file": f"work/{tid}.audit.json",
                                                    "recent": self.history(tid)}
        return 200, {"audit": info, "lease": {"id": lease_id, "beat_every_seconds": BEAT_EVERY,
                                                "lapses_after_seconds": LEASE_TTL}}

    def submit_audit(self, lease, body: bytes):
        tid = lease["step"]
        if len(body) > audits.MAX_SUBMISSION_BYTES:
            return 413, {"error": f"submissions are limited to {audits.MAX_SUBMISSION_BYTES} bytes"}
        try:
            sub = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            return 422, {"verdict": "REJECTED", "reasons": ["the submission is not valid JSON (UTF-8)"]}
        kind = sub.get("kind") if isinstance(sub, dict) else None
        if kind not in ("trigger", "clean"):
            return 422, {"verdict": "REJECTED", "reasons": ['the submission needs "kind": "trigger" or "kind": "clean"']}
        if sub.get("model") != tid:
            return 422, {"verdict": "REJECTED", "reasons": [f"the submission's model is {sub.get('model')!r}; this audit is {tid!r}"]}
        if self.audit_verdict(tid):
            self.db.execute("UPDATE leases SET state='withdrawn', ended=? WHERE id=?", (time.time(), lease["id"]))
            return 410, {"error": f"{tid} was resolved by someone else first; take the next audit"}
        sub_id = "S-" + secrets.token_hex(6)
        path = self.submissions_dir / f"{sub_id}.json"
        path.write_bytes(body)
        now = time.time()
        self.db.execute(
            "INSERT INTO submissions(id,lease,step,handle,created,sha256,path,status,kind) VALUES(?,?,?,?,?,?,?, 'queued', ?)",
            (sub_id, lease["id"], tid, lease["handle"], now, hashlib.sha256(body).hexdigest(), str(path), f"audit-{kind}"))
        self.db.execute("UPDATE leases SET state='submitted', reason='submitted', ended=? WHERE id=?", (now, lease["id"]))
        self.event("submitted", tid, lease["handle"], kind=f"audit-{kind}", submission=sub_id)
        self.queue.put(sub_id)
        position = self.db.execute("SELECT COUNT(*) FROM submissions WHERE status IN ('queued','checking')").fetchone()[0]
        return 202, {"submission": sub_id, "status": "queued", "position": position,
                     "next": "do not wait: take the next mission; the verdict will be at /desk/submission?id=" + sub_id}

    def _check_audit(self, row):
        from .nets import audit
        tid = row["step"]
        sub = json.loads(Path(row["path"]).read_bytes())
        model = audits.model(tid)
        if sub["kind"] == "trigger":
            res = audit.check_trigger(model, tid, sub)
        else:
            res = audit.check_clean(model, sub, deadline=time.time() + CERT_TIME_LIMIT)
        with self.lock:
            now = time.time()
            verdict = res.get("verdict")
            first = verdict and not self.audit_verdict(tid)
            pts = self.aprog.points if first and row["handle"] not in frontier.RESERVED_HANDLES else 0
            status = "accepted" if res.get("valid") else "rejected"
            self.db.execute(
                "UPDATE submissions SET status=?, result=?, checked=?, credited=?, points=?, reasons=? WHERE id=?",
                (status, json.dumps(res), now, 1 if first else 0, pts, json.dumps(res.get("problems", [])), row["id"]))
            if first:
                self.db.execute("INSERT INTO audits(target,verdict,handle,submission,detail,ts) VALUES(?,?,?,?,?,?)",
                                (tid, verdict, row["handle"], row["id"], json.dumps(res), now))
                for lease in self.active_leases(tid):
                    self.db.execute("UPDATE leases SET state='withdrawn', ended=? WHERE id=?", (now, lease["id"]))
                    self.event("withdrawn", tid, lease["handle"])
                self.event("resolved", tid, row["handle"], verdict=verdict, points=pts, submission=row["id"],
                           rate=res.get("rate"), unproved=res.get("unproved_in_region"))
            else:
                self.event("audit_checked", tid, row["handle"], kind=sub["kind"], valid=res.get("valid"),
                           rate=res.get("rate"), unproved=res.get("unproved_in_region"), slack=res.get("slack"),
                           problems=res.get("problems"), submission=row["id"])

    def audit_state(self, in_work: dict) -> dict | None:
        if not self.aprog:
            return None
        verdicts = {r["target"]: dict(r) for r in self.db.execute("SELECT * FROM audits")}
        subs = {r["step"]: r["n"] for r in self.db.execute(
            "SELECT step, COUNT(*) AS n FROM submissions WHERE kind LIKE 'audit-%' GROUP BY step")}
        rows = []
        for tid in self.audit_targets:
            v = verdicts.get(tid)
            rows.append({"id": tid, "status": "resolved" if v else ("in_work" if in_work.get(tid) else "open"),
                         "verdict": v["verdict"] if v else None, "by": v["handle"] if v else None,
                         "when": v["ts"] if v else None, "working": in_work.get(tid, []), "submissions": subs.get(tid, 0)})
        return self.aprog.public() | {"targets": rows, "stats": {
            "models": len(rows), "resolved": sum(1 for r in rows if r["verdict"]),
            "backdoors_found": sum(1 for r in rows if r["verdict"] == "BACKDOOR"),
            "certified_clean": sum(1 for r in rows if r["verdict"] == "CLEAN")}}

    def audit_detail(self, tid: str):
        t = self.audit_targets.get(tid)
        if not t:
            return 404, {"error": "no such audit model"}
        with self.lock:
            self.expire()
            v = self.audit_verdict(tid)
            out = t.public() | {"program_name": self.aprog.name, "summary": self.aprog.summary, "season": self.aprog.season,
                                "sources": self.aprog.sources,
                                "verdict": ({"verdict": v["verdict"], "by": v["handle"], "when": v["ts"],
                                             "detail": json.loads(v["detail"] or "{}")} if v else None),
                                "working": [r["handle"] for r in self.active_leases(tid)]}
            out["submissions"] = []
            for r in self.db.execute(
                    "SELECT id, handle, status, kind, result, points, credited, checked FROM submissions WHERE step=? AND kind LIKE 'audit-%' ORDER BY created DESC LIMIT 30",
                    (tid,)):
                res = json.loads(r["result"]) if r["result"] else {}
                out["submissions"].append({"id": r["id"], "handle": r["handle"], "status": r["status"],
                                           "kind": r["kind"][6:], "verdict": res.get("verdict"), "rate": res.get("rate"),
                                           "unproved": res.get("unproved_in_region"), "points": r["points"],
                                           "decisive": bool(r["credited"]), "checked": r["checked"]})
            out["history"] = [
                {"id": r["id"], "ts": r["ts"], "kind": r["kind"], "handle": r["handle"], "detail": json.loads(r["detail"] or "{}")}
                for r in self.db.execute("SELECT * FROM events WHERE step=? ORDER BY id DESC LIMIT 60", (tid,))]
            return 200, out

    # ---- treaty wargames ---------------------------------------------------------------------
    def regime_verdict(self, rid: str):
        return self.db.execute("SELECT * FROM wargames WHERE regime=?", (rid,)).fetchone()

    def open_regimes(self) -> list[str]:
        done = {r["regime"] for r in self.db.execute("SELECT regime FROM wargames")}
        return [r for r in self.regimes if r not in done]

    def _lease(self, step: str, handle: str, kind: str) -> str:
        lease_id = "L-" + secrets.token_hex(6)
        now = time.time()
        self.db.execute("INSERT INTO leases(id,step,handle,created,last_beat,state) VALUES(?,?,?,?,?, 'active')",
                        (lease_id, step, handle, now, now))
        self.event("taken", step, handle, kind=kind)
        return lease_id

    def _least_worked(self, cands: list[str]) -> str:
        active = {r["step"]: r["n"] for r in self.db.execute(
            "SELECT step, COUNT(*) AS n FROM leases WHERE state='active' GROUP BY step")}
        return min(cands, key=lambda c: (active.get(c, 0), int(re.sub(r"\D", "", c) or 0), c))

    def lease_info(self, lease_id: str) -> dict:
        return {"id": lease_id, "beat_every_seconds": BEAT_EVERY, "lapses_after_seconds": LEASE_TTL}

    def next_regime(self, handle: str, only: str | None = None):
        if not self.wprog:
            return 404, {"error": "the treaty wargames are not set up on this desk (they need AI Race; see rfd/settings.py)"}
        if only and self.regime_verdict(only):
            v = self.regime_verdict(only)
            return 409, {"error": f"{only} is already exploited, by {v['handle']}"}
        cands = [only] if only else self.open_regimes()
        if not cands:
            return 200, {"wargame": None, "lease": None, "message": "every regime has been exploited"}
        rid = self._least_worked(cands)
        reg = self.regimes[rid]
        params = wargame.params_for(reg)
        info = {"id": rid, "name": reg["name"], "overrides": reg["overrides"], "family_best": reg.get("family_best"),
                "labs": len(params.start), "start": list(params.start), "horizon": params.horizon,
                "runs": self.wprog.runs, "points": self.wprog.points, "program_name": self.wprog.name,
                "engine": str(self.wprog.airace_dir / "sources" / "race_env.py"),
                "docs": str(self.wprog.airace_dir / "docs" / "RACE_ENV.md"), "file": f"work/{rid}.strategy.json",
                "recent": self.history(rid)}
        return 200, {"wargame": info, "lease": self.lease_info(self._lease(rid, handle, "wargame"))}

    def submit_strategy(self, lease, body: bytes):
        rid = lease["step"]
        if len(body) > 256 * 1024:
            return 413, {"error": "a strategy must be at most 256 KiB"}
        try:
            sub = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            return 422, {"verdict": "REJECTED", "reasons": ["the strategy is not valid JSON (UTF-8)"]}
        if not isinstance(sub, dict) or sub.get("kind") != "strategy" or sub.get("regime") != rid:
            return 422, {"verdict": "REJECTED", "reasons": [f'needs "kind": "strategy" and "regime": "{rid}"']}
        problems = wargame.validate(sub, self.regimes[rid])
        if problems:
            return 422, {"verdict": "REJECTED", "reasons": problems}
        if self.regime_verdict(rid):
            self.db.execute("UPDATE leases SET state='withdrawn', ended=? WHERE id=?", (time.time(), lease["id"]))
            return 410, {"error": f"{rid} was exploited by someone else first; take the next mission"}
        return self._queue(lease, body, "strategy")

    def _queue(self, lease, body: bytes, kind: str):
        sub_id = "S-" + secrets.token_hex(6)
        path = self.submissions_dir / f"{sub_id}.json"
        path.write_bytes(body)
        now = time.time()
        self.db.execute(
            "INSERT INTO submissions(id,lease,step,handle,created,sha256,path,status,kind) VALUES(?,?,?,?,?,?,?, 'queued', ?)",
            (sub_id, lease["id"], lease["step"], lease["handle"], now, hashlib.sha256(body).hexdigest(), str(path), kind))
        self.db.execute("UPDATE leases SET state='submitted', reason='submitted', ended=? WHERE id=?", (now, lease["id"]))
        self.event("submitted", lease["step"], lease["handle"], kind=kind, submission=sub_id)
        self.queue.put(sub_id)
        position = self.db.execute("SELECT COUNT(*) FROM submissions WHERE status IN ('queued','checking')").fetchone()[0]
        return 202, {"submission": sub_id, "status": "queued", "position": position,
                     "next": "do not wait: take the next mission; the verdict will be at /desk/submission?id=" + sub_id}

    def _check_strategy(self, row):
        rid = row["step"]
        sub = json.loads(Path(row["path"]).read_bytes())
        res = wargame.check_strategy(rid, sub, judge=True)
        with self.lock:
            now = time.time()
            verdict = res.get("verdict")
            first = verdict and not self.regime_verdict(rid)
            pts = self.wprog.points if first and row["handle"] not in frontier.RESERVED_HANDLES else 0
            self.db.execute(
                "UPDATE submissions SET status=?, result=?, checked=?, credited=?, points=?, reasons=? WHERE id=?",
                ("accepted" if res.get("valid") else "rejected", json.dumps(res), now, 1 if first else 0, pts,
                 json.dumps(res.get("problems", [])), row["id"]))
            if first:
                self.db.execute("INSERT INTO wargames(regime,verdict,handle,submission,detail,ts) VALUES(?,?,?,?,?,?)",
                                (rid, verdict, row["handle"], row["id"], json.dumps(res), now))
                for lease in self.active_leases(rid):
                    self.db.execute("UPDATE leases SET state='withdrawn', ended=? WHERE id=?", (now, lease["id"]))
                    self.event("withdrawn", rid, lease["handle"])
                self.event("exploited", rid, row["handle"], gain=res["gain"], se=res["se"], points=pts, submission=row["id"])
            else:
                self.event("wargame_checked", rid, row["handle"], gain=res.get("gain"), se=res.get("se"),
                           bar=res.get("bar"), problems=res.get("problems"), submission=row["id"])

    def wargame_state(self, in_work: dict) -> dict | None:
        if not self.wprog:
            return None
        verdicts = {r["regime"]: dict(r) for r in self.db.execute("SELECT * FROM wargames")}
        best = {}
        for r in self.db.execute("SELECT step, result FROM submissions WHERE kind='strategy' AND status='accepted'"):
            g = json.loads(r["result"]).get("gain")
            if g is not None and g > best.get(r["step"], float("-inf")):
                best[r["step"]] = g
        rows = []
        for rid, reg in self.regimes.items():
            v = verdicts.get(rid)
            rows.append({"id": rid, "name": reg["name"], "family_best": reg.get("family_best"),
                         "status": "exploited" if v else ("in_work" if in_work.get(rid) else "open"),
                         "by": v["handle"] if v else None, "when": v["ts"] if v else None,
                         "best_gain": best.get(rid), "working": in_work.get(rid, [])})
        return self.wprog.public() | {"targets": rows, "stats": {
            "regimes": len(rows), "exploited": sum(1 for r in rows if r["status"] == "exploited")}}

    def wargame_detail(self, rid: str):
        reg = self.regimes.get(rid)
        if not reg:
            return 404, {"error": "no such regime"}
        with self.lock:
            v = self.regime_verdict(rid)
            out = {"id": rid, "name": reg["name"], "overrides": reg["overrides"], "family_best": reg.get("family_best"),
                   "program_name": self.wprog.name, "summary": self.wprog.summary, "source": self.wprog.source,
                   "runs": self.wprog.runs, "points": self.wprog.points,
                   "verdict": ({"by": v["handle"], "when": v["ts"], "detail": json.loads(v["detail"] or "{}"),
                                "strategy": json.loads(Path(self.db.execute("SELECT path FROM submissions WHERE id=?",
                                                                            (v["submission"],)).fetchone()["path"]).read_text())}
                               if v else None),
                   "working": [r["handle"] for r in self.active_leases(rid)], "submissions": []}
            for r in self.db.execute("SELECT id, handle, status, result, points, credited, checked FROM submissions "
                                     "WHERE step=? AND kind='strategy' ORDER BY created DESC LIMIT 30", (rid,)):
                res = json.loads(r["result"]) if r["result"] else {}
                out["submissions"].append({"id": r["id"], "handle": r["handle"], "status": r["status"],
                                           "gain": res.get("gain"), "se": res.get("se"), "exploit": bool(r["credited"]),
                                           "checked": r["checked"]})
            out["history"] = [
                {"id": r["id"], "ts": r["ts"], "kind": r["kind"], "handle": r["handle"], "detail": json.loads(r["detail"] or "{}")}
                for r in self.db.execute("SELECT * FROM events WHERE step=? ORDER BY id DESC LIMIT 60", (rid,))]
            return 200, out

    # ---- intelligence desk -------------------------------------------------------------------
    def next_intel(self, handle: str, only: str | None = None):
        if not self.iprog:
            return 404, {"error": "the intelligence desk is not set up on this desk (it needs Futuras; see rfd/settings.py)"}
        ms = intel.missions()
        if only and only not in ms:
            return 404, {"error": f"no intel mission {only}"}
        cands = [only] if only else sorted(ms, key=lambda m: ms[m]["latest"])   # stalest first
        if not cands:
            return 200, {"intel": None, "lease": None, "message": "no intel missions"}
        active = {r["step"]: r["n"] for r in self.db.execute(
            "SELECT step, COUNT(*) AS n FROM leases WHERE state='active' GROUP BY step")}
        mid = min(cands, key=lambda m: (active.get(m, 0), ms[m]["latest"]))
        info = ms[mid] | {"program_name": self.iprog.name, "judge": self.iprog.judge,
                          "codebook": str(self.iprog.futuras / "docs" / "VIEWS_CODEBOOK.md"),
                          "views_file": str(self.iprog.futuras / "lib" / "views.json"),
                          "map": f"{self.iprog.futuras_url}?view=consistency&p={ms[mid]['person']}",
                          "file": f"work/{mid}.intel.json", "points_base": self.iprog.points_base,
                          "points_per_stance": self.iprog.points_per_stance}
        return 200, {"intel": info, "lease": self.lease_info(self._lease(mid, handle, "intel"))}

    def submit_intel(self, lease, body: bytes):
        mid = lease["step"]
        if len(body) > intel.MAX_BYTES:
            return 413, {"error": f"an intel record must be at most {intel.MAX_BYTES} bytes"}
        try:
            sub = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            return 422, {"verdict": "REJECTED", "reasons": ["the record is not valid JSON (UTF-8)"]}
        mission = intel.missions().get(mid)
        if not isinstance(sub, dict) or sub.get("kind") != "intel" or not mission:
            return 422, {"verdict": "REJECTED", "reasons": ['needs "kind": "intel"']}
        problems = intel.validate(sub, mission, self.iprog.max_urls)
        if problems:
            return 422, {"verdict": "REJECTED", "reasons": problems}
        return self._queue(lease, body, "intel")

    def _check_intel(self, row):
        sub = json.loads(Path(row["path"]).read_bytes())
        mission = intel.missions().get(row["step"])
        res = intel.check_quotes(sub, mission)
        with self.lock:
            status = "review" if res["ok"] else "rejected"
            self.db.execute("UPDATE submissions SET status=?, result=?, checked=?, reasons=? WHERE id=?",
                            (status, json.dumps({k: v for k, v in res.items() if k != "log"}), time.time(),
                             json.dumps([] if res["ok"] else [res["summary"]]), row["id"]))
            self.db.execute("UPDATE submissions SET log=? WHERE id=?", (res.get("log", "")[-6000:], row["id"]))
            self.event("intel_checked", row["step"], row["handle"], ok=res["ok"], summary=res["summary"], submission=row["id"])

    def review(self, sub_id: str, accept: bool, reason: str = "", points: int | None = None):
        """Human review of an intel record (called by tools/review.py, never over HTTP)."""
        with self.lock:
            row = self.db.execute("SELECT * FROM submissions WHERE id=?", (sub_id,)).fetchone()
            if not row or row["kind"] != "intel" or row["status"] != "review":
                return False, "no intel record awaiting review with that id"
            sub = json.loads(Path(row["path"]).read_bytes())
            pts = (intel.points_for(sub) if points is None else points) if accept else 0
            self.db.execute("UPDATE submissions SET status=?, credited=?, points=?, reasons=? WHERE id=?",
                            ("accepted" if accept else "rejected", 1 if accept else 0, pts,
                             json.dumps([] if accept else [reason or "not accepted on review"]), sub_id))
            self.event("intel_accepted" if accept else "intel_declined", row["step"], row["handle"],
                       points=pts, stances=len(sub.get("stances", [])), submission=sub_id,
                       reason=None if accept else (reason or "not accepted on review"))
            return True, pts

    def intel_state(self, in_work: dict) -> dict | None:
        if not self.iprog:
            return None
        ms = intel.missions()
        counts = {}
        for r in self.db.execute("SELECT step, status, COUNT(*) AS n FROM submissions WHERE kind='intel' GROUP BY step, status"):
            counts.setdefault(r["step"], {})[r["status"]] = r["n"]
        rows = [m | {"working": in_work.get(mid, []), "review": counts.get(mid, {}).get("review", 0),
                     "accepted": counts.get(mid, {}).get("accepted", 0)} for mid, m in sorted(ms.items(), key=lambda kv: kv[1]["latest"])]
        accepted = []
        for r in self.db.execute("SELECT id, step, handle, path, checked FROM submissions WHERE kind='intel' AND status='accepted' "
                                 "ORDER BY checked DESC LIMIT 20"):
            sub = json.loads(Path(r["path"]).read_text())
            accepted.append({"id": r["id"], "mission": r["step"], "handle": r["handle"], "when": r["checked"],
                             "statements": [{"title": s.get("title"), "date": s.get("date"), "url": s.get("url")} for s in sub.get("statements", [])],
                             "stances": [{"dimension": st.get("dimension"), "value": st.get("value"), "status": st.get("status"),
                                          "summary": st.get("summary"), "evidence": st.get("evidence")} for st in sub.get("stances", [])]})
        return self.iprog.public() | {"targets": rows, "accepted": accepted, "stats": {
            "people": len(rows), "awaiting_review": sum(r["review"] for r in rows), "accepted": sum(r["accepted"] for r in rows)}}

    def record_public(self, target_id: str):
        r = self.record(target_id)
        if not r:
            return None
        return {"bound": r["bound"], "proved": r["proved"], "total": r["total"], "work": r["work"],
                "leaves": r["leaves"], "by": r["handle"], "when": r["ts"], "submission": r["submission"]}

    def beat(self, lease_id: str):
        with self.lock:
            self.expire()
            row = self.db.execute("SELECT * FROM leases WHERE id=?", (lease_id,)).fetchone()
            if not row:
                return 404, {"stop": True, "why": "no such lease"}
            if row["state"] != "active":
                why = {"expired": "the lease lapsed: no beat for 15 minutes",
                       "withdrawn": "the step was settled by someone else",
                       "released": "you released it", "submitted": "you already submitted it"}.get(row["state"], row["state"])
                return 410, {"stop": True, "why": why}
            if row["step"] in self.regimes and self.regime_verdict(row["step"]):
                self.db.execute("UPDATE leases SET state='withdrawn', ended=? WHERE id=?", (time.time(), lease_id))
                return 410, {"stop": True, "why": "the regime was exploited by someone else"}
            if row["step"] in self.audit_targets and self.audit_verdict(row["step"]):
                self.db.execute("UPDATE leases SET state='withdrawn', ended=? WHERE id=?", (time.time(), lease_id))
                return 410, {"stop": True, "why": "the model was resolved by someone else"}
            if row["step"] in self.steps and self.settled(row["step"]):
                self.db.execute("UPDATE leases SET state='withdrawn', ended=? WHERE id=?", (time.time(), lease_id))
                return 410, {"stop": True, "why": "the step was settled by someone else"}
            self.db.execute("UPDATE leases SET last_beat=? WHERE id=?", (time.time(), lease_id))
            return 200, {"ok": True, "step": row["step"]}

    def release(self, lease_id: str, reason: str):
        with self.lock:
            if reason not in RELEASE_REASONS or reason == "submitted":
                return 400, {"error": "reason must be one of " + ", ".join(r for r in RELEASE_REASONS if r != "submitted")}
            row = self.db.execute("SELECT * FROM leases WHERE id=?", (lease_id,)).fetchone()
            if not row:
                return 404, {"error": "no such lease"}
            if row["state"] != "active":
                return 410, {"error": f"lease is {row['state']}"}
            self.db.execute("UPDATE leases SET state='released', reason=?, ended=? WHERE id=?", (reason, time.time(), lease_id))
            self.event("released", row["step"], row["handle"], reason=reason)
            return 200, {"ok": True}

    def submit(self, lease_id: str, body: bytes):
        with self.lock:
            self.expire()
            row = self.db.execute("SELECT * FROM leases WHERE id=?", (lease_id,)).fetchone()
            if not row:
                return 404, {"error": "no such lease"}
            if row["state"] != "active":
                return 410, {"error": f"lease is {row['state']}; do not resend, take the next step"}
            if row["step"] in self.targets:
                return self.submit_certificate(row, body)
            if row["step"] in self.audit_targets:
                return self.submit_audit(row, body)
            if row["step"] in self.regimes:
                return self.submit_strategy(row, body)
            if intel.MISSION_ID.match(row["step"]):
                return self.submit_intel(row, body)
            step = self.steps[row["step"]]
            if len(body) > rules.MAX_BYTES:
                return 413, {"error": f"a Lean file must be at most {rules.MAX_BYTES} bytes"}
            if self.settled(step.id):
                self.db.execute("UPDATE leases SET state='withdrawn', ended=? WHERE id=?", (time.time(), lease_id))
                return 410, {"error": "the step was settled first by someone else; take the next step"}
            merged = registry.merged_modules() - {step.module}
            refusals, notes, stripped = rules.check(
                body, lambda m: m == "Mathlib" or m.startswith("Mathlib.") or m.startswith("ReportForDuty.Defs.") or m in merged)
            sub_id = "S-" + secrets.token_hex(6)
            digest = hashlib.sha256(body).hexdigest()
            path = self.submissions_dir / f"{sub_id}.lean"
            path.write_bytes(body)
            now = time.time()
            if refusals:
                self.db.execute(
                    "INSERT INTO submissions(id,lease,step,handle,created,sha256,path,status,reasons,checked) VALUES(?,?,?,?,?,?,?, 'rejected', ?, ?)",
                    (sub_id, lease_id, step.id, row["handle"], now, digest, str(path), json.dumps(refusals), now))
                self.event("rejected", step.id, row["handle"], reasons=refusals, submission=sub_id)
                return 422, {"submission": sub_id, "verdict": "REJECTED", "reasons": refusals,
                             "note": "refused by the format rules before building; fix the file and submit again under the same lease"}
            kind, problem = checker.submitted_kind(stripped, step.lean)
            if problem:
                self.db.execute(
                    "INSERT INTO submissions(id,lease,step,handle,created,sha256,path,status,reasons,checked) VALUES(?,?,?,?,?,?,?, 'rejected', ?, ?)",
                    (sub_id, lease_id, step.id, row["handle"], now, digest, str(path), json.dumps([problem]), now))
                return 422, {"submission": sub_id, "verdict": "REJECTED", "reasons": [problem]}
            self.db.execute(
                "INSERT INTO submissions(id,lease,step,handle,created,sha256,path,status,kind) VALUES(?,?,?,?,?,?,?, 'queued', ?)",
                (sub_id, lease_id, step.id, row["handle"], now, digest, str(path), kind))
            self.db.execute("UPDATE leases SET state='submitted', reason='submitted', ended=? WHERE id=?", (now, lease_id))
            self.event("submitted", step.id, row["handle"], kind=kind, submission=sub_id)
            self.queue.put(sub_id)
            position = self.db.execute("SELECT COUNT(*) FROM submissions WHERE status IN ('queued','checking')").fetchone()[0]
            return 202, {"submission": sub_id, "status": "queued", "position": position, "notes": notes,
                         "next": "do not wait: take the next step; the verdict will be at /desk/submission?id=" + sub_id}

    def submit_certificate(self, lease, body: bytes):
        tgt = self.targets[lease["step"]]
        if len(body) > frontier.MAX_CERT_BYTES:
            return 413, {"error": f"certificates are limited to {frontier.MAX_CERT_BYTES} bytes"}
        try:
            cert = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            return 422, {"verdict": "REJECTED", "reasons": ["the certificate is not valid JSON (UTF-8)"]}
        reasons = []
        if not isinstance(cert, dict) or not isinstance(cert.get("classes"), dict):
            reasons.append("the certificate needs a 'classes' object")
        elif cert.get("model") != tgt.model:
            reasons.append(f"the certificate's model is {cert.get('model')!r}; this target is {tgt.model!r}")
        if reasons:
            return 422, {"verdict": "REJECTED", "reasons": reasons, "note": "fix it and submit again under the same lease"}
        sub_id = "S-" + secrets.token_hex(6)
        path = self.submissions_dir / f"{sub_id}.json"
        path.write_bytes(body)
        now = time.time()
        self.db.execute(
            "INSERT INTO submissions(id,lease,step,handle,created,sha256,path,status,kind) VALUES(?,?,?,?,?,?,?, 'queued', 'certificate')",
            (sub_id, lease["id"], tgt.id, lease["handle"], now, hashlib.sha256(body).hexdigest(), str(path)))
        self.db.execute("UPDATE leases SET state='submitted', reason='submitted', ended=? WHERE id=?", (now, lease["id"]))
        self.event("submitted", tgt.id, lease["handle"], kind="certificate", submission=sub_id)
        self.queue.put(sub_id)
        position = self.db.execute("SELECT COUNT(*) FROM submissions WHERE status IN ('queued','checking')").fetchone()[0]
        return 202, {"submission": sub_id, "status": "queued", "position": position,
                     "next": "do not wait: take the next target; the verdict will be at /desk/submission?id=" + sub_id}

    def _check_certificate(self, row):
        from .nets import certificate
        tgt = self.targets[row["step"]]
        cert = json.loads(Path(row["path"]).read_bytes())
        res = certificate.check(frontier.model(tgt.model), cert, deadline=time.time() + CERT_TIME_LIMIT)
        summary = res.summary()
        with self.lock:
            now = time.time()
            old = self.record(tgt.id)
            old_proved = int(old["proved"]) if old else 0
            advanced = res.proved_inputs > old_proved
            pts = frontier.points_for(old["bound"] if old else 0.0, float(res.bound), tgt.track) if advanced else 0
            if row["handle"] in frontier.RESERVED_HANDLES:
                pts = 0
            summary["previous_record"] = old["bound"] if old else None
            summary["advanced"] = advanced
            self.db.execute(
                "UPDATE submissions SET status='accepted', result=?, seconds=?, checked=?, credited=?, points=?, reasons=? WHERE id=?",
                (json.dumps(summary), res.seconds, now, 1 if advanced else 0, pts, json.dumps(res.errors[:20]), row["id"]))
            if advanced:
                self.db.execute(
                    "INSERT OR REPLACE INTO frontier(target,proved,total,bound,work,leaves,handle,submission,ts) VALUES(?,?,?,?,?,?,?,?,?)",
                    (tgt.id, str(res.proved_inputs), str(res.total_inputs), float(res.bound), str(res.work),
                     res.leaves_checked, row["handle"], row["id"], now))
                self.event("advanced", tgt.id, row["handle"], old=old["bound"] if old else None, new=float(res.bound),
                           points=pts, work=res.work, leaves=res.leaves_checked, submission=row["id"])
            else:
                self.event("checked", tgt.id, row["handle"], bound=float(res.bound),
                           record=old["bound"] if old else None, submission=row["id"])
        if advanced and self.merge:
            frontier.CERTS_DIR.mkdir(parents=True, exist_ok=True)
            (frontier.CERTS_DIR / f"{tgt.id}.json").write_bytes(Path(row["path"]).read_bytes())

    def submission(self, sub_id: str):
        row = self.db.execute("SELECT * FROM submissions WHERE id=?", (sub_id,)).fetchone()
        if not row:
            return 404, {"error": "no such submission"}
        out = {k: row[k] for k in ("id", "step", "handle", "status", "kind", "seconds", "credited")}
        out["created"], out["checked"] = row["created"], row["checked"]
        out["verdict"] = {"accepted": "ACCEPTED", "rejected": "REJECTED", "fault": "FAULT",
                          "review": "AWAITING REVIEW"}.get(row["status"])
        out["reasons"] = json.loads(row["reasons"] or "[]")
        out["log"] = row["log"] or ""
        if row["kind"] in ("certificate", "strategy", "intel") or (row["kind"] or "").startswith("audit-"):
            out["result"] = json.loads(row["result"]) if row["result"] else None
            out["points"] = row["points"]
        return 200, out

    # ---- the checker queue ---------------------------------------------------------------
    def _worker(self):
        while True:
            sub_id = self.queue.get()
            try:
                self._check_one(sub_id)
            except Exception as exc:  # keep the worker alive; record the fault
                with self.lock:
                    self.db.execute("UPDATE submissions SET status='fault', reasons=? WHERE id=?",
                                    (json.dumps([f"checker error: {exc}"]), sub_id))

    def _check_one(self, sub_id: str):
        with self.lock:
            row = self.db.execute("SELECT * FROM submissions WHERE id=?", (sub_id,)).fetchone()
            if not row or row["status"] not in ("queued",):
                return
            self.db.execute("UPDATE submissions SET status='checking', tries=tries+1 WHERE id=?", (sub_id,))
        handler = (self._check_strategy if row["step"] in self.regimes else
                   self._check_intel if row["kind"] == "intel" else None)
        if handler:
            try:
                handler(row)
            except Exception as exc:
                with self.lock:
                    self.db.execute("UPDATE submissions SET status='rejected', reasons=?, checked=? WHERE id=?",
                                    (json.dumps([f"could not check the submission: {exc}"]), time.time(), sub_id))
                    self.event("rejected", row["step"], row["handle"], reasons=[f"could not check the submission: {exc}"],
                               submission=sub_id)
            return
        if row["step"] in self.audit_targets:
            try:
                self._check_audit(row)
            except Exception as exc:
                with self.lock:
                    self.db.execute("UPDATE submissions SET status='rejected', reasons=?, checked=? WHERE id=?",
                                    (json.dumps([f"could not check the submission: {exc}"]), time.time(), sub_id))
                    self.event("rejected", row["step"], row["handle"], reasons=[f"could not check the submission: {exc}"],
                               submission=sub_id)
            return
        if row["step"] in self.targets:
            try:
                self._check_certificate(row)
            except Exception as exc:
                with self.lock:
                    self.db.execute("UPDATE submissions SET status='rejected', reasons=?, checked=? WHERE id=?",
                                    (json.dumps([f"could not check the certificate: {exc}"]), time.time(), sub_id))
                    self.event("rejected", row["step"], row["handle"], reasons=[f"could not check the certificate: {exc}"],
                               submission=sub_id)
            return
        body = Path(row["path"]).read_bytes()
        v = checker.check(row["step"], body)
        with self.lock:
            now = time.time()
            if v.verdict == "FAULT" and row["tries"] < 2:
                self.db.execute("UPDATE submissions SET status='queued', reasons=? WHERE id=?", (json.dumps(v.reasons), sub_id))
                self.event("fault", row["step"], row["handle"], reasons=v.reasons, submission=sub_id)
                self.queue.put(sub_id)
                return
            status = {"ACCEPTED": "accepted", "REJECTED": "rejected", "FAULT": "fault"}[v.verdict]
            self.db.execute("UPDATE submissions SET status=?, kind=?, reasons=?, log=?, seconds=?, checked=? WHERE id=?",
                            (status, v.kind, json.dumps(v.reasons), v.log[-6000:], v.seconds, now, sub_id))
            if v.verdict != "ACCEPTED":
                self.event("rejected" if v.verdict == "REJECTED" else "fault", row["step"], row["handle"],
                           reasons=v.reasons, submission=sub_id)
                return
            if self.settled(row["step"]):
                self.event("accepted_late", row["step"], row["handle"], submission=sub_id)
                return
            step = self.steps[row["step"]]
            self.db.execute("INSERT INTO settled(step,kind,handle,submission,points,ts) VALUES(?,?,?,?,?,?)",
                            (step.id, v.kind, row["handle"], sub_id, step.points, now))
            self.db.execute("UPDATE submissions SET credited=1 WHERE id=?", (sub_id,))
            for lease in self.active_leases(step.id):
                self.db.execute("UPDATE leases SET state='withdrawn', ended=? WHERE id=?", (now, lease["id"]))
                self.event("withdrawn", step.id, lease["handle"])
            self.event("proved" if v.kind == "prove" else "refuted", step.id, row["handle"],
                       points=step.points, submission=sub_id, seconds=v.seconds)
        if self.merge:
            self._merge(step, body)

    def _merge(self, step, body: bytes):
        """Accepted proofs join the library so later steps can import them."""
        registry.STEPS_DIR.mkdir(parents=True, exist_ok=True)
        target = registry.STEPS_DIR / f"{step.lean}.lean"
        target.write_bytes(body)
        subprocess.run(["lake", "build", step.module], cwd=registry.LEAN_DIR, capture_output=True, text=True)

    # ---- public read model ---------------------------------------------------------------
    def state(self) -> dict:
        with self.lock:
            self.expire()
            settled = {r["step"]: dict(r) for r in self.db.execute("SELECT * FROM settled")}
            pending = {r["step"] for r in self.db.execute("SELECT step FROM submissions WHERE status IN ('queued','checking')")}
            leases = [dict(r) for r in self.db.execute("SELECT * FROM leases WHERE state='active' ORDER BY created")]
            in_work: dict[str, list[str]] = {}
            for l in leases:
                in_work.setdefault(l["step"], []).append(l["handle"])
            programs = []
            totals = {"steps": 0, "proved": 0, "refuted": 0, "open": 0, "in_work": 0, "checking": 0, "points_available": 0}
            for prog in self.programs.values():
                if prog.hidden:
                    continue
                p = prog.public()
                p["steps"] = []
                for step in prog.steps:
                    s = step.public()
                    st = settled.get(step.id)
                    if st:
                        s["status"] = "proved" if st["kind"] == "prove" else "refuted"
                        s["by"], s["when"] = st["handle"], st["ts"]
                    elif step.id in pending:
                        s["status"] = "checking"
                    elif step.id in in_work:
                        s["status"] = "in_work"
                    else:
                        s["status"] = "open"
                    s["working"] = in_work.get(step.id, [])
                    totals["steps"] += 1
                    totals[s["status"]] = totals.get(s["status"], 0) + 1
                    if not st:
                        totals["points_available"] += step.points
                    p["steps"].append(s)
                programs.append(p)
            rows: dict[str, dict] = {}
            for r in self.db.execute(
                    """SELECT handle, SUM(points) AS points, SUM(kind='prove') AS proofs, SUM(kind='refute') AS refutations,
                              MAX(ts) AS last FROM settled WHERE step NOT LIKE 'TEST-%' GROUP BY handle"""):
                rows[r["handle"]] = {"handle": r["handle"], "points": r["points"] or 0, "proofs": r["proofs"] or 0,
                                     "refutations": r["refutations"] or 0, "advances": 0, "last": r["last"]}
            for r in self.db.execute(
                    """SELECT handle, SUM(points) AS points, SUM(kind='certificate') AS advances,
                              SUM(kind LIKE 'audit-%') AS audits, SUM(kind='strategy') AS exploits,
                              SUM(kind='intel') AS intel, MAX(checked) AS last FROM submissions
                       WHERE (kind IN ('certificate', 'strategy', 'intel') OR kind LIKE 'audit-%') AND credited=1 GROUP BY handle"""):
                if r["handle"] in frontier.RESERVED_HANDLES:
                    continue
                d = rows.setdefault(r["handle"], {"handle": r["handle"], "points": 0, "proofs": 0, "refutations": 0,
                                                  "advances": 0, "last": 0})
                d["points"] += r["points"] or 0
                d["advances"] = r["advances"] or 0
                d["audits"] = r["audits"] or 0
                d["exploits"] = r["exploits"] or 0
                d["intel"] = r["intel"] or 0
                d["last"] = max(d["last"] or 0, r["last"] or 0)
            board = sorted(rows.values(), key=lambda d: (-d["points"], d["last"] or 0))
            agents_now = sorted({l["handle"] for l in leases})
            queue_rows = [dict(r) for r in self.db.execute(
                "SELECT id, step, handle, status, created FROM submissions WHERE status IN ('queued','checking') ORDER BY created")]
            checked = self.db.execute("SELECT COUNT(*) FROM submissions WHERE status IN ('accepted','rejected')").fetchone()[0]
            return {
                "generated": time.time(),
                "frontier": self.frontier_state(in_work),
                "audits": self.audit_state(in_work),
                "wargames": self.wargame_state(in_work),
                "intel": self.intel_state(in_work),
                "programs": programs,
                "totals": totals | {"agents_now": len(agents_now), "submissions_checked": checked},
                "leaderboard": board,
                "live": [{"handle": l["handle"], "step": l["step"], "since": l["created"], "last_beat": l["last_beat"],
                          "kind": ("target" if l["step"] in self.targets else "audit" if l["step"] in self.audit_targets
                                   else "wargame" if l["step"] in self.regimes else "intel" if l["step"].startswith("I-") else "step")}
                         for l in leases if not l["step"].startswith("TEST-")],
                "queue": queue_rows,
                "feed": self.feed(limit=40),
                "prizes": self.prizes.state(),
                "media": self.media.state(),
            }

    def frontier_state(self, in_work: dict) -> list[dict]:
        records = {r["target"]: dict(r) for r in self.db.execute("SELECT * FROM frontier")}
        subs = {r["step"]: r["n"] for r in self.db.execute(
            "SELECT step, COUNT(*) AS n FROM submissions WHERE kind='certificate' GROUP BY step")}
        out = []
        for prog in self.fprograms.values():
            p = prog.public()
            p["tracks"] = []
            for tr in prog.tracks:
                tg = [t for t in self.targets.values() if t.track is tr]
                rows = []
                for t in sorted(tg, key=lambda t: t.seed):
                    r = records.get(t.id)
                    rows.append({"id": t.id, "seed": t.seed, "bound": r["bound"] if r else None,
                                 "work": r["work"] if r else None, "leaves": r["leaves"] if r else None,
                                 "by": r["handle"] if r else None, "when": r["ts"] if r else None,
                                 "working": in_work.get(t.id, []), "submissions": subs.get(t.id, 0)})
                certified = [x["bound"] for x in rows if x["bound"] is not None]
                stats = {"models": len(rows), "certified": len(certified),
                         "mean_certified": (sum(certified) / len(certified)) if certified else None,
                         "mean_all": (sum(certified) / len(rows)) if rows else None,
                         "best": max(certified) if certified else None}
                p["tracks"].append(tr.public() | {"stats": stats, "targets": rows})
            out.append(p)
        return out

    def target_detail(self, target_id: str):
        t = self.targets.get(target_id)
        if not t:
            return 404, {"error": "no such target"}
        with self.lock:
            self.expire()
            out = t.public() | {"track_name": t.track.name, "published": t.track.published,
                                "source": t.track.program.source, "program_name": t.track.program.name}
            out["record"] = self.record_public(t.id)
            out["working"] = [r["handle"] for r in self.active_leases(t.id)]
            out["submissions"] = []
            for r in self.db.execute(
                    "SELECT id, handle, status, result, points, credited, checked FROM submissions WHERE step=? AND kind='certificate' ORDER BY created DESC LIMIT 30",
                    (t.id,)):
                res = json.loads(r["result"]) if r["result"] else {}
                out["submissions"].append({"id": r["id"], "handle": r["handle"], "status": r["status"],
                                           "bound": res.get("bound"), "work": res.get("work"), "leaves": res.get("leaves_checked"),
                                           "points": r["points"], "advanced": bool(r["credited"]), "checked": r["checked"]})
            out["history"] = [
                {"id": r["id"], "ts": r["ts"], "kind": r["kind"], "handle": r["handle"], "detail": json.loads(r["detail"] or "{}")}
                for r in self.db.execute("SELECT * FROM events WHERE step=? ORDER BY id DESC LIMIT 60", (t.id,))]
            return 200, out

    def step_detail(self, step_id: str):
        step = self.steps.get(step_id)
        if not step or step.program.hidden:
            return 404, {"error": "no such step"}
        with self.lock:
            self.expire()
            out = step.public()
            out["program_name"] = step.program.name
            out["source"] = step.program.source
            out["reviewed"] = step.program.reviewed
            out["status"] = self.status_of(step.id)
            out["working"] = [r["handle"] for r in self.active_leases(step.id)]
            st = self.settled(step.id)
            out["by"], out["when"] = (st["handle"], st["ts"]) if st else (None, None)
            proof = registry.STEPS_DIR / f"{step.lean}.lean"
            out["proof"] = proof.read_text(encoding="utf-8") if st and proof.exists() else None
            out["history"] = [
                {"id": r["id"], "ts": r["ts"], "kind": r["kind"], "handle": r["handle"],
                 "detail": json.loads(r["detail"] or "{}")}
                for r in self.db.execute("SELECT * FROM events WHERE step=? ORDER BY id DESC LIMIT 60", (step.id,))]
            return 200, out

    def feed(self, after: int = 0, limit: int = 100) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM events WHERE id > ? AND (step IS NULL OR step NOT LIKE 'TEST-%') ORDER BY id DESC LIMIT ?",
            (after, limit)).fetchall()
        return [{"id": r["id"], "ts": r["ts"], "kind": r["kind"], "step": r["step"], "handle": r["handle"],
                 "detail": json.loads(r["detail"] or "{}")} for r in rows]

    def reset(self):
        with self.lock:
            for table in ("leases", "submissions", "settled", "events", "frontier", "audits", "wargames"):
                self.db.execute(f"DELETE FROM {table}")


# ---- HTTP --------------------------------------------------------------------------------
class Bucket:
    """Per-client rate limit for desk calls: a few requests a second."""

    def __init__(self, rate: float = 3.0, burst: float = 10.0):
        self.rate, self.burst, self.state, self.lock = rate, burst, {}, threading.Lock()

    def allow(self, key: str) -> bool:
        with self.lock:
            tokens, last = self.state.get(key, (self.burst, time.time()))
            now = time.time()
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            if tokens < 1:
                self.state[key] = (tokens, now)
                return False
            self.state[key] = (tokens - 1, now)
            return True


CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "text/javascript; charset=utf-8", ".txt": "text/plain; charset=utf-8",
                 ".svg": "image/svg+xml", ".lean": "text/plain; charset=utf-8", ".ico": "image/x-icon",
                 ".json": "application/json; charset=utf-8", ".mp4": "video/mp4", ".jpg": "image/jpeg",
                 ".png": "image/png"}


def make_handler(desk: Desk, public_url: str, bucket: "Bucket | None" = None):
    bucket = bucket or Bucket()

    class Handler(BaseHTTPRequestHandler):
        server_version = "rfd-desk"
        sys_version = ""

        def log_message(self, fmt, *args):  # quiet; events are in the database
            pass

        def send(self, code: int, payload, ctype="application/json; charset=utf-8", extra=None):
            body = payload if isinstance(payload, bytes) else (
                payload.encode() if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False).encode())
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            if ctype.startswith("text/html"):
                self.send_header("Content-Security-Policy",
                                 "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
                                 "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def params(self):
            q = parse_qs(urlparse(self.path).query)
            return {k: v[0] for k, v in q.items()}

        def limited(self) -> bool:
            if not bucket.allow(self.client_address[0]):
                self.send(429, {"error": "too many requests: one every few seconds at most"})
                return True
            return False

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            path = urlparse(self.path).path
            p = self.params()
            if path == "/desk/next":
                if self.limited():
                    return
                handle = p.get("handle", "")
                if not HANDLE.match(handle):
                    return self.send(400, {"error": "handle must look like a GitHub handle"})
                level = p.get("level")
                if level and level not in registry.LEVELS:
                    return self.send(400, {"error": "level must be one of " + ", ".join(registry.LEVELS)})
                code, out = desk.next(handle, level, p.get("program"), p.get("hard") == "1", p.get("another") == "1",
                                      p.get("track"), p.get("target"))
                return self.send(code, out)
            if path == "/desk/submission":
                return self.send(*desk.submission(p.get("id", "")))
            if path == "/desk/claim":
                if self.limited():
                    return
                return self.send(*desk.prizes.claim(p.get("lease", "")))
            if path == "/api/prize/verify":
                if self.limited():
                    return
                return self.send(*desk.prizes.verify(p.get("pledge", ""), p.get("code", "")))
            if path == "/api/state":
                return self.send(200, desk.state())
            if path == "/api/views":
                snap = views.load(desk.iprog.futuras) if desk.iprog else None
                return self.send(200, snap) if snap else self.send(404, {"error": "the Futuras map of views is not available"})
            if path == "/api/feed":
                try:
                    after = int(p.get("after", "0"))
                except ValueError:
                    after = 0
                return self.send(200, desk.feed(after=after))
            m = re.match(r"^/api/wargame/(W\d{1,3})$", path)
            if m:
                return self.send(*desk.wargame_detail(m.group(1)))
            m = re.match(r"^/api/audit/(A\d{1,3})$", path)
            if m:
                return self.send(*desk.audit_detail(m.group(1)))
            m = re.match(r"^/api/target/(K\d{1,2}-\d{1,6})$", path)
            if m:
                return self.send(*desk.target_detail(m.group(1)))
            m = re.match(r"^/api/certificate/(K\d{1,2}-\d{1,6})$", path)
            if m:
                f = frontier.CERTS_DIR / f"{m.group(1)}.json"
                if m.group(1) not in desk.targets or not f.exists() or not desk.record(m.group(1)):
                    return self.send(404, {"error": "no certificate on record for that target"})
                return self.send(200, f.read_bytes(), "application/json; charset=utf-8",
                                 {"Content-Disposition": f'attachment; filename="{m.group(1)}.cert.json"'})
            m = re.match(r"^/api/step/([A-Z]{1,6}-\d{2,3})$", path)
            if m:
                return self.send(*desk.step_detail(m.group(1)))
            m = re.match(r"^/api/proof/([A-Z]{1,6}-\d{2,3})$", path)
            if m:
                step = desk.steps.get(m.group(1))
                f = registry.STEPS_DIR / f"{step.lean}.lean" if step else None
                if not f or not f.exists() or not desk.settled(step.id):
                    return self.send(404, {"error": "no accepted proof for that step"})
                return self.send(200, f.read_bytes(), CONTENT_TYPES[".lean"])
            if path == "/join.txt":
                text = (SITE_DIR / "join.txt").read_text(encoding="utf-8").replace("{{DESK}}", public_url)
                return self.send(200, text, CONTENT_TYPES[".txt"])
            # static site
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            target = (SITE_DIR / rel).resolve()
            if SITE_DIR.resolve() not in target.parents or not target.is_file() or target.name == "join.txt":
                return self.send(404, "not found", "text/plain; charset=utf-8")
            return self.send(200, target.read_bytes(), CONTENT_TYPES.get(target.suffix, "application/octet-stream"))

        def do_POST(self):
            path = urlparse(self.path).path
            p = self.params()
            if not path.startswith("/desk/"):
                return self.send(404, {"error": "not found"})
            if self.limited():
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length > frontier.MAX_CERT_BYTES:
                return self.send(413, {"error": f"the file must be at most {frontier.MAX_CERT_BYTES} bytes"})
            body = self.rfile.read(length) if length else b""
            if path == "/desk/pledge":
                if length > 4096:
                    return self.send(413, {"error": "a pledge is at most 4 KB"})
                return self.send(*desk.prizes.pledge(body))
            if path == "/desk/media":
                if length > 4096:
                    return self.send(413, {"error": "a submission is at most 4 KB"})
                return self.send(*desk.media.submit(body))
            lease = p.get("lease", "")
            if path == "/desk/beat":
                return self.send(*desk.beat(lease))
            if path == "/desk/release":
                return self.send(*desk.release(lease, p.get("reason", "")))
            if path == "/desk/submit":
                return self.send(*desk.submit(lease, body))
            return self.send(404, {"error": "not found"})

    return Handler


def main(argv=None) -> int:
    import os
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(var, "1")
    try:
        os.nice(10)   # checking is background work; never starve the machine
    except OSError:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--db", default=str(DATA_DIR / "desk.db"))
    ap.add_argument("--public-url", default=None, help="URL printed in join.txt (default http://host:port)")
    ap.add_argument("--no-merge", action="store_true", help="do not write accepted proofs into lean/")
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args(argv)
    desk = Desk(Path(args.db), merge=not args.no_merge)
    if args.reset:
        desk.reset()
        print("desk reset")
        return 0
    url = args.public_url or f"http://{args.host}:{args.port}"
    server = ThreadingHTTPServer((args.host, args.port), make_handler(desk, url))
    print(f"desk serving {url}  (db {args.db})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
