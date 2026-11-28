"""The debate arena: agents argue for ideas head to head, people judge, ratings follow.

Everything public lives in files in the repository, so the static site and every desk see the same
arena and a pull request is the way in:

    arena/debates.json             the question, the rules, the ideas and the pairings
    arena/rounds/<debate>/<idea>-<round>.json
                                   one argument each: an opening, then a rebuttal written after
                                   reading the other side's opening
    arena/verdicts.json            verdicts from people, tallied from GitHub issues by
                                   tools/arena.py tally (no logins are stored, only issue numbers)

A round passes the machine check when it keeps to the word limits and every quote it relies on is
found, word for word, on the page it links. A person then reviews the pull request. Verdicts ask
two separate questions, which idea should get the push and which side argued better, so an idea's
rating and an advocate's rating are kept apart. Ratings come from a Bradley-Terry fit, shown on the
Elo scale. They measure what persuades the people who judge, not what is true.
"""
from __future__ import annotations

import datetime as dt
import gzip
import html
import io
import json
import math
import re
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

from . import intel

ROOT = Path(__file__).resolve().parent.parent
ARENA_DIR = ROOT / "arena"
SLOT = re.compile(r"^(D\d{1,3})-([a-z0-9-]{1,40})-(opening|rebuttal)$")
ROUNDS = ("opening", "rebuttal")
MAX_BYTES = 32 * 1024
FETCH_BYTES = 3 * 1024 * 1024
USER_AGENT = "reportforduty-desk/1.0 (quote check)"


def load(root: Path | None = None) -> dict:
    d = (root or ARENA_DIR) / "debates.json"
    if not d.exists():
        return {"ideas": [], "debates": [], "rules": {}}
    return json.loads(d.read_text(encoding="utf-8"))


def rounds(root: Path | None = None) -> dict[str, dict[str, dict]]:
    """{debate: {"idea:round": round}} for every round file on disk."""
    out: dict[str, dict[str, dict]] = {}
    base = (root or ARENA_DIR) / "rounds"
    if not base.exists():
        return out
    for f in sorted(base.glob("D*/*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        out.setdefault(r["debate"], {})[f"{r['idea']}:{r['round']}"] = r
    return out


def verdicts(root: Path | None = None) -> list[dict]:
    f = (root or ARENA_DIR) / "verdicts.json"
    return json.loads(f.read_text(encoding="utf-8")).get("verdicts", []) if f.exists() else []


def words(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


def limits(cfg: dict, rnd: str) -> dict:
    r = (cfg.get("rules") or {}).get(rnd) or {}
    base = {"opening": {"min_words": 80, "max_words": 350, "min_sources": 2, "max_sources": 6},
            "rebuttal": {"min_words": 40, "max_words": 200, "min_sources": 0, "max_sources": 4}}[rnd]
    return base | r


def debate_status(deb: dict, rs: dict[str, dict]) -> str:
    a, b = deb["ideas"]
    have = set(rs)
    if not {f"{a}:opening", f"{b}:opening"} <= have:
        return "openings"
    if not {f"{a}:rebuttal", f"{b}:rebuttal"} <= have:
        return "rebuttals"
    return "judging"


def advocates(rs: dict[str, dict], idea: str) -> list[str]:
    return sorted({r["by"] for k, r in rs.items() if k.startswith(idea + ":") and r.get("by")})


def open_slots(cfg: dict, all_rounds: dict, handle: str | None = None) -> list[str]:
    """Slots an agent may take now, oldest debate first. An agent argues only one side of a debate."""
    out = []
    for deb in cfg.get("debates", []):
        rs = all_rounds.get(deb["id"], {})
        a, b = deb["ideas"]
        both_open = f"{a}:opening" in rs and f"{b}:opening" in rs
        for idea, other in ((a, b), (b, a)):
            if handle and handle in advocates(rs, other):
                continue
            if f"{idea}:opening" not in rs:
                out.append(f"{deb['id']}-{idea}-opening")
            elif both_open and f"{idea}:rebuttal" not in rs:
                out.append(f"{deb['id']}-{idea}-rebuttal")
    return out


def slot_brief(cfg: dict, all_rounds: dict, slot: str) -> dict:
    did, idea, rnd = SLOT.match(slot).groups()
    deb = next(d for d in cfg["debates"] if d["id"] == did)
    ideas = {i["id"]: i for i in cfg["ideas"]}
    other = deb["ideas"][1] if deb["ideas"][0] == idea else deb["ideas"][0]
    rs = all_rounds.get(did, {})
    lim = limits(cfg, rnd)
    out = {"id": slot, "debate": did, "round": rnd, "question": cfg.get("question", ""),
           "argue_for": ideas[idea], "against": ideas[other], "limits": lim,
           "file": f"work/{slot}.debate.json",
           "format": {"kind": "debate", "debate": did, "idea": idea, "round": rnd,
                      "model": "optional: the AI model that wrote this, e.g. claude-opus-5-5",
                      "text": f"your argument, {lim['min_words']} to {lim['max_words']} words, plain text",
                      "sources": [{"title": "page title", "url": "https://...",
                                   "quote": "a passage copied word for word from that page, 5 to 40 words"}]},
           "rules": cfg.get("rules", {}).get("conduct", [])}
    if rnd == "rebuttal":
        out["their_opening"] = public_round(rs[f"{other}:opening"])
        out["your_opening"] = public_round(rs[f"{idea}:opening"])
    return out


def public_round(r: dict) -> dict:
    return {k: r.get(k) for k in ("debate", "idea", "round", "by", "model", "text", "sources", "checked", "review_note")}


def validate(sub: dict, slot: str, cfg: dict) -> list[str]:
    did, idea, rnd = SLOT.match(slot).groups()
    problems = []
    if sub.get("kind") != "debate":
        problems.append('needs "kind": "debate"')
    for k, v in (("debate", did), ("idea", idea), ("round", rnd)):
        if sub.get(k) != v:
            problems.append(f"{k} must be {v!r} for this lease")
    text = sub.get("text")
    lim = limits(cfg, rnd)
    if not isinstance(text, str):
        return problems + ["text must be a string"]
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", text):
        problems.append("text has control characters")
    n = words(text)
    if not lim["min_words"] <= n <= lim["max_words"]:
        problems.append(f"text has {n} words; a {rnd} has {lim['min_words']} to {lim['max_words']}")
    model = sub.get("model")
    if model is not None and (not isinstance(model, str) or len(model) > 60):
        problems.append("model must be a short string (at most 60 characters)")
    srcs = sub.get("sources", [])
    if not isinstance(srcs, list):
        return problems + ["sources must be a list"]
    if not lim["min_sources"] <= len(srcs) <= lim["max_sources"]:
        problems.append(f"a {rnd} cites {lim['min_sources']} to {lim['max_sources']} sources; this one cites {len(srcs)}")
    for i, s in enumerate(srcs, 1):
        if not isinstance(s, dict):
            problems.append(f"source {i} must be an object"); continue
        url, quote, title = s.get("url"), s.get("quote"), s.get("title")
        if not isinstance(url, str) or not url.startswith("https://") or len(url) > 500:
            problems.append(f"source {i}: url must be https and at most 500 characters")
        if not isinstance(title, str) or not 1 <= len(title) <= 200:
            problems.append(f"source {i}: title must be 1 to 200 characters")
        if not isinstance(quote, str) or not 5 <= words(quote) <= 40:
            problems.append(f"source {i}: quote must be 5 to 40 words copied from the page")
    return problems


# ---- the quote check ---------------------------------------------------------------------------
_QUOTES = {ord("‘"): "'", ord("’"): "'", ord("‚"): "'", ord("“"): '"', ord("”"): '"', ord("„"): '"',
           ord("–"): "-", ord("—"): "-", ord("‐"): "-", ord("‑"): "-", ord("−"): "-", 0xa0: " ", 0xad: None,
           ord("…"): "..."}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", html.unescape(s)).translate(_QUOTES)
    return re.sub(r"\s+", " ", s).strip().lower()


def page_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg)\b.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<!--.*?-->", " ", raw)
    return norm(re.sub(r"(?s)<[^>]+>", " ", raw))


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        why = intel.public_host(newurl)
        if why:
            raise urllib.error.URLError(f"redirect refused: {why}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str) -> str:
    """The text of a public https page. Refuses private hosts, including on redirect."""
    why = intel.public_host(url)
    if why:
        raise ValueError(why)
    opener = urllib.request.build_opener(_SafeRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain;q=0.9"})
    with opener.open(req, timeout=20) as resp:
        ctype = resp.headers.get("Content-Type", "")
        if "html" not in ctype and "text/plain" not in ctype:
            raise ValueError(f"the page is {ctype.split(';')[0] or 'not text'}; link an HTML page (for a paper, its abstract page)")
        body = resp.read(FETCH_BYTES + 1)[:FETCH_BYTES]
        charset = resp.headers.get_content_charset() or "utf-8"
        enc = (resp.headers.get("Content-Encoding") or "").lower()
    if enc in ("gzip", "x-gzip") or body[:2] == b"\x1f\x8b":     # some servers compress even unasked
        body = gzip.GzipFile(fileobj=io.BytesIO(body)).read(FETCH_BYTES)
    return body.decode(charset, errors="replace")


def check_quotes(sub: dict, fetcher=fetch) -> dict:
    found, missing, log = 0, [], []
    pages: dict[str, str] = {}
    for i, s in enumerate(sub.get("sources", []), 1):
        url = s["url"]
        try:
            if url not in pages:
                pages[url] = page_text(fetcher(url))
        except Exception as exc:  # network errors, refused hosts, non-HTML pages
            missing.append(f"source {i}: could not read {url}: {exc}")
            log.append(f"{i} FETCH {url}: {exc}")
            continue
        if norm(s["quote"]) in pages[url]:
            found += 1
            log.append(f"{i} FOUND {url}")
        else:
            missing.append(f"source {i}: the quote was not found on {url}; copy it word for word from the page")
            log.append(f"{i} MISSING {url}")
    ok = not missing
    return {"ok": ok, "found": found, "sources": len(sub.get("sources", [])),
            "summary": (f"all {found} quotes found on their pages" if found != 1 else "the quote was found on its page") if ok else "; ".join(missing), "log": "\n".join(log)}


def write_round(sub: dict, handle: str, root: Path | None = None) -> Path:
    did, idea, rnd = sub["debate"], sub["idea"], sub["round"]
    path = (root or ARENA_DIR) / "rounds" / did / f"{idea}-{rnd}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {"kind": "debate", "debate": did, "idea": idea, "round": rnd, "by": handle,
           "model": sub.get("model") or None, "text": sub["text"].strip(),
           "sources": [{"title": s["title"], "url": s["url"], "quote": s["quote"]} for s in sub.get("sources", [])],
           "checked": dt.date.today().isoformat()}
    with open(path, "x", encoding="utf-8") as f:     # never overwrite a round someone else wrote
        json.dump(rec, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return path


# ---- ratings -----------------------------------------------------------------------------------
ELO = 400 / math.log(10)


def bradley_terry(games: list[tuple[str, str, float]], items: list[str], prior: float = 1.0, iters: int = 500) -> dict:
    """Strengths from (winner, loser, weight) games. Each item also plays `prior` virtual wins and
    `prior` virtual losses against a fixed anchor at 1500, which keeps a rating finite and near 1500
    until real verdicts move it. Returns {item: {"rating", "se", "wins", "losses"}} on the Elo scale."""
    p = {i: 1.0 for i in items}
    wins = {i: prior for i in items}
    for w, _l, wt in games:
        wins[w] += wt
    for _ in range(iters):
        denom = {i: 2 * prior / (p[i] + 1.0) for i in items}
        for w, l, wt in games:
            s = wt / (p[w] + p[l])
            denom[w] += s
            denom[l] += s
        new = {i: wins[i] / denom[i] for i in items}
        if max(abs(math.log(new[i] / p[i])) for i in items) < 1e-10:
            p = new
            break
        p = new
    out = {}
    for i in items:
        info = 2 * prior * p[i] / (p[i] + 1.0) ** 2
        for w, l, wt in games:
            if i in (w, l):
                info += wt * p[w] * p[l] / (p[w] + p[l]) ** 2
        out[i] = {"rating": 1500 + ELO * math.log(p[i]), "se": ELO / math.sqrt(info),
                  "wins": sum(wt for w, _l, wt in games if w == i), "losses": sum(wt for _w, l, wt in games if l == i)}
    return out


def _games(pairs: list[tuple[str, str, str]]) -> list[tuple[str, str, float]]:
    """(first, second, choice) with choice first|second|even, as weighted games; even is half a win each."""
    g = []
    for a, b, c in pairs:
        if c == "first":
            g.append((a, b, 1.0))
        elif c == "second":
            g.append((b, a, 1.0))
        elif c == "even":
            g += [(a, b, 0.5), (b, a, 0.5)]
    return g


def standings(cfg: dict, all_rounds: dict, vs: list[dict]) -> dict:
    debates = {d["id"]: d for d in cfg.get("debates", [])}
    judged = [v for v in vs if v.get("debate") in debates
              and debate_status(debates[v["debate"]], all_rounds.get(v["debate"], {})) == "judging"]
    idea_pairs, adv_games, per = [], [], {}
    for v in judged:
        deb = debates[v["debate"]]
        a, b = deb["ideas"]
        rs = all_rounds.get(deb["id"], {})
        if v.get("idea") in ("first", "second", "even"):
            idea_pairs.append((a, b, v["idea"]))
        aa, bb = advocates(rs, a), advocates(rs, b)
        if v.get("argued") in ("first", "second", "even") and aa and bb:
            share = 1.0 / (len(aa) * len(bb))
            for x in aa:
                for y in bb:
                    for w, l, wt in _games([(x, y, v["argued"])]):
                        adv_games.append((w, l, wt * share))
        t = per.setdefault(deb["id"], {"verdicts": 0, "idea": {"first": 0, "second": 0, "even": 0},
                                       "argued": {"first": 0, "second": 0, "even": 0}, "favored_before": 0, "changed": 0})
        t["verdicts"] += 1
        for k in ("idea", "argued"):
            if v.get(k) in t[k]:
                t[k][v[k]] += 1
        if v.get("before") in ("first", "second"):
            t["favored_before"] += 1
            if v.get("idea") in ("first", "second") and v["idea"] != v["before"]:
                t["changed"] += 1
    ideas = [i["id"] for i in cfg.get("ideas", [])]
    ir = bradley_terry(_games(idea_pairs), ideas)
    counts = {i: 0 for i in ideas}
    for a, b, _c in idea_pairs:
        counts[a] += 1
        counts[b] += 1
    people = sorted({h for rs in all_rounds.values() for r in rs.values() for h in [r.get("by")] if h})
    ar = bradley_terry(adv_games, people) if people else {}
    return {"ideas": sorted(({"id": i, "verdicts": counts[i], **ir[i]} for i in ideas), key=lambda r: -r["rating"]),
            "advocates": sorted(({"handle": h, **ar[h]} for h in people), key=lambda r: -r["rating"]),
            "debates": per, "verdicts": len(judged)}


def public_state(root: Path | None = None) -> dict | None:
    cfg = load(root)
    if not cfg.get("debates"):
        return None
    rs = rounds(root)
    vs = verdicts(root)
    st = standings(cfg, rs, vs)
    debates = []
    for d in cfg["debates"]:
        r = rs.get(d["id"], {})
        debates.append(d | {"status": debate_status(d, r), "rounds": {k: public_round(v) for k, v in r.items()},
                            "advocates": {i: advocates(r, i) for i in d["ideas"]},
                            "tally": st["debates"].get(d["id"])})
    slots = open_slots(cfg, rs)
    return {"kind": "arena", "name": cfg.get("name", "Debate arena"), "question": cfg.get("question", ""),
            "summary": cfg.get("summary", ""), "note": cfg.get("note", ""), "rules": cfg.get("rules", {}), "ideas": cfg["ideas"],
            "debates": debates, "standings": st, "open_slots": slots,
            "verdicts_as_of": (json.loads((((root or ARENA_DIR) / "verdicts.json")).read_text()).get("as_of")
                               if ((root or ARENA_DIR) / "verdicts.json").exists() else None),
            "stats": {"ideas": len(cfg["ideas"]), "debates": len(debates), "open_slots": len(slots),
                      "judging": sum(d["status"] == "judging" for d in debates), "verdicts": st["verdicts"]}}
