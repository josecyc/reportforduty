"""The intelligence desk: keep the Futuras map of views current.

A mission is one person on the map. A submission is a small record in the Futuras views format:

    {"kind": "intel", "person": "hinton",
     "statements": [{"id": "hinton-2026-...", "people": ["hinton"], "title": ..., "kind": ..., "date": ...,
                     "url": "https://...", "publisher": ..., "read": "full", "readNote": ""}],
     "stances": [{"statement": ..., "person": "hinton", "dimension": ..., "status": ..., "value": ...,
                  "detail": ..., "condition": "", "summary": ..., "url": ..., "section": ...,
                  "evidence": "verbatim passage", "revises": null, "revisionEvidence": ""}],
     "allegations": []}

Machine checks: structure against the codebook; every URL is https and resolves only to public
addresses (no loopback, private or link-local hosts, so the desk cannot be pointed at internal
services); every passage is found on its page by Futuras' own checker. Then a person reviews the
placements (tools/review.py). Nothing an agent writes is shown to other agents, and summaries are
shown on the site only after review.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from .registry import PROGRAMS_DIR
from . import settings

MISSION_ID = re.compile(r"^I-[a-z0-9-]{1,40}$")
SCALES = {
    "arrival": [1, 2, 3, 4], "takeoff": [1, 2, 3, 4], "growth": [1, 2, 3, 4], "catastrophe": [1, 2, 3, 4],
    "worry": ["misalignment", "power", "misuse", "disempowerment", "hype", "other"],
    "handover": [1, 2, 3, 4], "autonomy": [1, 2, 3], "pace": [1, 2, 3, 4], "power": [1, 2, 3, 4], "rivalry": [1, 2, 3, 4],
}
DATE = re.compile(r"^\d{4}(-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?)?$")
MAX_BYTES = 512 * 1024


@dataclass
class Program:
    id: str
    name: str
    question: str
    summary: str
    why: str
    futuras: Path
    futuras_url: str
    points_base: int
    points_per_stance: int
    max_urls: int
    judge: str

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "question": self.question, "summary": self.summary,
                "why": self.why, "futuras_url": self.futuras_url, "judge": self.judge,
                "points_base": self.points_base, "points_per_stance": self.points_per_stance, "kind": "intel"}


@lru_cache(maxsize=1)
def load() -> Program | None:
    for path in sorted(PROGRAMS_DIR.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("kind") == "intel":
            fut = settings.path_setting("RFD_FUTURAS", "futuras_dir")
            if not fut or not (fut / "lib" / "views.json").exists():
                return None      # Futuras is optional: without it there is no intel desk
            return Program(raw["id"], raw["name"], raw["question"], raw["summary"], raw.get("why", ""), fut,
                           raw.get("futuras_url", ""), int(raw.get("points_base", 5)),
                           int(raw.get("points_per_stance", 2)), int(raw.get("max_urls", 20)), raw.get("judge", ""))
    return None


def views() -> dict:
    prog = load()
    if not prog:
        return {"people": [], "statements": [], "stances": []}
    f = prog.futuras / "lib" / "views.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"people": [], "statements": [], "stances": []}


def missions() -> dict[str, dict]:
    v = views()
    last: dict[str, str] = {}
    count: dict[str, int] = {}
    for s in v.get("statements", []):
        for p in s.get("people", []):
            last[p] = max(last.get(p, ""), s.get("date", ""))
            count[p] = count.get(p, 0) + 1
    out = {}
    for p in v.get("people", []):
        out[f"I-{p['id']}"] = {"id": f"I-{p['id']}", "person": p["id"], "name": p["name"], "role": p.get("role", ""),
                                "latest": last.get(p["id"], ""), "statements": count.get(p["id"], 0)}
    return out


def public_host(url: str) -> str | None:
    """None if the URL is https on a host that resolves only to public addresses; else the reason."""
    try:
        u = urlparse(url)
    except ValueError:
        return "not a URL"
    if u.scheme != "https" or not u.hostname:
        return "only https URLs are accepted"
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return f"{u.hostname} does not resolve"
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return f"{u.hostname} resolves to a non-public address"
    return None


def validate(sub: dict, mission: dict, max_urls: int) -> list[str]:
    problems = []
    person = mission["person"]
    if sub.get("person") != person:
        problems.append(f"person must be {person!r}")
    sts, stances = sub.get("statements"), sub.get("stances")
    if not isinstance(sts, list) or not sts or not isinstance(stances, list) or not stances:
        return problems + ["a record needs at least one statement and one stance"]
    known = {s["id"] for s in views().get("statements", [])}
    ids = set()
    for s in sts:
        if not isinstance(s, dict):
            problems.append("statements must be objects"); continue
        if s.get("id") in known:
            problems.append(f"statement {s.get('id')} is already on the map")
        ids.add(s.get("id"))
        if person not in (s.get("people") or []):
            problems.append(f"statement {s.get('id')}: people must include {person}")
        if not DATE.match(str(s.get("date", ""))):
            problems.append(f"statement {s.get('id')}: date must be YYYY-MM-DD (or YYYY-MM, YYYY)")
        if not s.get("url"):
            problems.append(f"statement {s.get('id')}: url is required")
    for st in stances:
        if not isinstance(st, dict):
            problems.append("stances must be objects"); continue
        at = f"stance {st.get('dimension')} in {st.get('statement')}"
        if st.get("statement") not in ids:
            problems.append(f"{at}: statement is not in this record")
        if st.get("person") != person:
            problems.append(f"{at}: person must be {person}")
        dim = st.get("dimension")
        if dim not in SCALES:
            problems.append(f"{at}: unknown dimension")
        elif st.get("status") not in ("stated", "conditional", "declined"):
            problems.append(f"{at}: status must be stated, conditional or declined")
        elif st.get("status") != "declined" and st.get("value") not in SCALES[dim]:
            problems.append(f"{at}: value {st.get('value')!r} is not on the scale")
        if st.get("status") == "conditional" and not st.get("condition"):
            problems.append(f"{at}: a conditional stance needs its condition")
        if not st.get("evidence") or len(str(st.get("evidence")).split()) > 60:
            problems.append(f"{at}: evidence must be a verbatim passage of at most 60 words")
        if not st.get("url"):
            problems.append(f"{at}: url is required")
    urls = {s.get("url") for s in sts if isinstance(s, dict)} | {st.get("url") for st in stances if isinstance(st, dict)}
    urls |= {s.get("checkUrl") for s in sts if isinstance(s, dict) and s.get("checkUrl")}
    urls.discard(None)
    if len(urls) > max_urls:
        problems.append(f"at most {max_urls} distinct URLs per record")
    for u in sorted(urls):
        why = public_host(str(u))
        if why:
            problems.append(f"{u}: {why}")
    return problems


def check_quotes(sub: dict, mission: dict) -> dict:
    """Run Futuras' own passage checker on the record. Needs node and network."""
    prog = load()
    person = next((p for p in views().get("people", []) if p["id"] == mission["person"]), None)
    record = {"people": [person], "statements": sub["statements"], "stances": sub["stances"],
              "allegations": sub.get("allegations", [])}
    with tempfile.TemporaryDirectory(prefix="rfd-intel-") as d:
        f = Path(d) / "record.json"
        f.write_text(json.dumps(record, ensure_ascii=False))
        try:
            r = subprocess.run(["node", str(prog.futuras / "tools" / "check-forecast-record.mjs"), str(f)],
                               cwd=prog.futuras, capture_output=True, text=True, timeout=600)
        except (OSError, subprocess.TimeoutExpired) as e:
            return {"ok": False, "summary": f"could not run the checker: {e}", "log": ""}
    out = r.stdout + r.stderr
    m = re.search(r"(\d+) passages: (\d+) matched, (\d+) not on page, (\d+) unreachable, (\d+) without a passage", out)
    if not m:
        return {"ok": False, "summary": "the checker gave no summary", "log": out[-4000:]}
    total, matched, missing, unreachable, none = map(int, m.groups())
    ok = r.returncode == 0 and matched == total and total > 0
    return {"ok": ok, "summary": m.group(0), "passages": total, "matched": matched, "missing": missing,
            "unreachable": unreachable, "log": out[-4000:]}


def points_for(sub: dict) -> int:
    prog = load()
    return prog.points_base + prog.points_per_stance * len(sub.get("stances", []))
