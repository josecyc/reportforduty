"""The Futuras map of views, read live for the map's "where people disagree" panels.

Futuras keeps its ten questions (and their answer scales) in lib/views.ts and every placement in
lib/views.json, each with the passage it was coded from and the page it is on. This module reads
both without running any of Futuras' code: the DIMENSIONS literal in views.ts is plain JavaScript
object syntax, which a small tokenizer turns into JSON.

A person's current placement on a question is their most recent dated statement that addresses
it (Futuras' own rule, views.ts currentOf). Results are cached until either file changes.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|[A-Za-z_]\w*|-?\d+(?:\.\d+)?|[{}\[\]:,]|\s+|//[^\n]*|/\*.*?\*/', re.S)
_cache: dict = {}


class ViewsError(ValueError):
    pass


def js_literal_to_json(text: str):
    """Parse a JavaScript array/object literal (double-quoted strings, bare keys, trailing commas)."""
    out: list[str] = []
    toks = []
    pos = 0
    for m in _TOKEN.finditer(text):
        if m.start() != pos:
            raise ViewsError(f"unexpected text at {pos}: {text[pos:pos + 30]!r}")
        pos = m.end()
        t = m.group(0)
        if t.isspace() or t.startswith("//") or t.startswith("/*"):
            continue
        toks.append(t)
    if pos != len(text):
        raise ViewsError(f"unexpected text at {pos}: {text[pos:pos + 30]!r}")
    for i, t in enumerate(toks):
        if re.match(r"[A-Za-z_]", t):
            if i + 1 < len(toks) and toks[i + 1] == ":":
                out.append(json.dumps(t))
            elif t in ("true", "false", "null"):
                out.append(t)
            else:
                raise ViewsError(f"bare identifier {t!r} is not a key")
        elif t in "]}" and out and out[-1] == ",":
            out[-1] = t
        else:
            out.append(t)
    return json.loads("".join(out))


def parse_dimensions(ts: str) -> tuple[str, list]:
    m = re.search(r"export const DIMENSIONS: Dimension\[\] = (\[.*?\n\]);", ts, re.S)
    if not m:
        raise ViewsError("DIMENSIONS not found in views.ts")
    as_of = re.search(r'export const VIEWS_AS_OF = "([^"]+)"', ts)
    return (as_of.group(1) if as_of else ""), js_literal_to_json(m.group(1))


def current_placements(data: dict) -> dict:
    """{dimension: [placement, ...]} with each person's most recent stance on that dimension."""
    statements = {s["id"]: s for s in data["statements"]}
    people = {p["id"]: p for p in data["people"]}
    date = lambda s: (statements.get(s["statement"]) or {}).get("date") or ""
    latest: dict[tuple[str, str], dict] = {}
    for s in sorted(data["stances"], key=date):  # stable: same-date stances keep file order, last wins
        latest[(s["person"], s["dimension"])] = s
    out: dict[str, list] = {}
    for (person, dim), s in latest.items():
        st = statements.get(s["statement"]) or {}
        out.setdefault(dim, []).append({
            "person": person, "name": (people.get(person) or {}).get("name", person),
            "short": (people.get(person) or {}).get("short", person),
            "value": s["value"], "status": s["status"], "detail": s.get("detail", ""),
            "condition": s.get("condition", ""), "summary": s.get("summary", ""),
            "evidence": s.get("evidence", ""), "url": s.get("url") or st.get("url"),
            "date": st.get("date", ""), "title": st.get("title", ""), "publisher": st.get("publisher", ""),
        })
    for rows in out.values():
        rows.sort(key=lambda r: r["short"].lower())
    return out


def load(futuras: Path) -> dict | None:
    """The views snapshot for the site, or None when Futuras is not there or cannot be read."""
    vj, vt = futuras / "lib" / "views.json", futuras / "lib" / "views.ts"
    try:
        key = (str(futuras), vj.stat().st_mtime_ns, vt.stat().st_mtime_ns)
    except OSError:
        return None
    if _cache.get("key") == key:
        return _cache["data"]
    try:
        data = json.loads(vj.read_text(encoding="utf-8"))
        as_of, dims = parse_dimensions(vt.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    snapshot = {
        "as_of": as_of,
        "dimensions": dims,
        "people": {p["id"]: {"name": p["name"], "short": p["short"], "role": p.get("role", "")} for p in data["people"]},
        "current": current_placements(data),
        "counts": {"people": len(data["people"]), "statements": len(data["statements"]), "placements": len(data["stances"])},
    }
    _cache.update(key=key, data=snapshot)
    return snapshot
