#!/usr/bin/env python3
"""Render the introduction video (site/media/intro.mp4 and a poster) from the site's own data.

    python3 tools/make_intro_video.py                     # the video and the poster
    python3 tools/make_intro_video.py --stills 3,12,24    # PNG frames at those seconds, to check layout

Motion graphics drawn frame by frame with Pillow and encoded with ffmpeg (both required). The
needs, their status and the counts come from site/map.json and site/efforts.json, so running it
again after the content changes keeps the video true. It uses macOS system fonts (Iowan Old
Style, Helvetica Neue, Menlo) and runs at low priority. No narration: every word is on screen.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
W, H = 1920, 1080
FPS = 30
DURATION = 71.0

BG, PANEL = (245, 244, 239), (255, 255, 255)
INK, INK2, INK3 = (22, 24, 26), (70, 75, 81), (111, 117, 124)
LINE, ACCENT, ACCENT_SOFT = (221, 219, 210), (29, 106, 58), (226, 240, 229)
TERM_BG, TERM_INK, TERM_GREEN = (22, 24, 26), (236, 236, 230), (120, 200, 150)
# (ink, background, label), as the chips on the site's map
STATUS = {
    "open": ((29, 106, 58), (226, 240, 229), "Missions open"),
    "review": ((133, 86, 0), (248, 237, 214), "Reviewed missions"),
    "practice": ((39, 90, 140), (225, 236, 247), "Practice only"),
    "guide": ((83, 64, 176), (235, 232, 250), "Start here"),
    "curated": ((39, 90, 140), (225, 236, 247), "Open to contributions"),
    "none": ((111, 117, 124), (236, 235, 229), "No mission yet"),
}
FONTS = {"serif": "/System/Library/Fonts/Supplemental/Iowan Old Style.ttc",
         "sans": "/System/Library/Fonts/HelveticaNeue.ttc", "mono": "/System/Library/Fonts/Menlo.ttc"}
FACE = {("serif", False): 0, ("serif", True): 1, ("sans", False): 0, ("sans", True): 10, ("mono", False): 0, ("mono", True): 1}
_fonts = {}


def font(kind, size, bold=False):
    key = (kind, size, bold)
    if key not in _fonts:
        try:
            _fonts[key] = ImageFont.truetype(FONTS[kind], size, index=FACE[(kind, bold)])
        except OSError:
            _fonts[key] = ImageFont.load_default(size)
    return _fonts[key]


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def ease(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def prog(t, start, dur):
    return ease((t - start) / dur)


def window(t, start, end, fade=0.6):
    """1 inside [start, end], fading in and out over `fade` seconds."""
    return clamp(min((t - start) / fade, (end - t) / fade))


def mix(c1, c2, a):
    return tuple(round(c1[i] + (c2[i] - c1[i]) * clamp(a)) for i in range(3))


def wrap(s, f, width):
    lines, cur = [], ""
    for w in s.split():
        test = f"{cur} {w}".strip()
        if not cur or f.getlength(test) <= width:
            cur = test
        else:
            lines.append(cur)
            cur = w
    return lines + ([cur] if cur else [])


def text(d, xy, s, f, color, a=1.0, under=BG, anchor="la"):
    if a > 0.01:
        d.text(xy, s, font=f, fill=mix(under, color, a), anchor=anchor)


def load():
    m = json.loads((ROOT / "site" / "map.json").read_text(encoding="utf-8"))
    e = json.loads((ROOT / "site" / "efforts.json").read_text(encoding="utf-8"))

    def status(n):  # the same rule as needStatus() in site/app.js, with every theater running
        kinds = [t["kind"] for t in n.get("theaters") or []]
        if any(k in ("audit", "wargame", "frontier") for k in kinds):
            return "open"
        for k, st in (("intel", "review"), ("training", "practice"), ("guide", "guide"), ("gallery", "curated")):
            if k in kinds:
                return st
        return "none"

    regions = {r["id"]: r for r in m["regions"]}
    axes = [{"title": a["title"], "gloss": a["gloss"],
             "needs": [(nid, m["needs"][nid]["title"], status(m["needs"][nid])) for rid in a["regions"] for nid in regions[rid]["needs"]]}
            for a in m["axes"]]
    feature = m["needs"]["audit"]
    return {"axes": axes, "n": sum(len(a["needs"]) for a in axes), "orgs": len(e["orgs"]),
            "efforts": sum(len(o.get("efforts") or []) for o in e["orgs"]), "instruments": len(e.get("instruments") or []),
            "feature": (feature["title"], feature["question"], status(feature))}


def chip(d, x, y, st, a, size=24):
    ink, bg, label = STATUS[st]
    f = font("sans", size, True)
    w = f.getlength(label) + 2 * 14 + 22
    d.rounded_rectangle((x, y, x + w, y + size + 18), radius=(size + 18) // 2, fill=mix(BG, bg, a))
    d.ellipse((x + 14, y + (size + 18) / 2 - 6, x + 26, y + (size + 18) / 2 + 6), fill=mix(bg, ink, a))
    text(d, (x + 34, y + (size + 18) / 2), label, f, ink, a, under=bg, anchor="lm")
    return w


def grid(d, D, t, start, a_all, dim_none=0.0, glow=0.0):
    """The map: one column per axis, one tile per need, coloured by status."""
    col_w, x0, y0, tile_h, gap = 520, 160, 292, 60, 9
    k = 0
    for i, ax in enumerate(D["axes"]):
        x = x0 + i * (col_w + 30)
        text(d, (x, 228), ax["title"], font("serif", 44, True), INK, a_all)
        for j, (_, title, st) in enumerate(ax["needs"]):
            p = prog(t, start + k * 0.1, 0.5) * a_all
            k += 1
            if p <= 0.01:
                continue
            y = y0 + j * (tile_h + gap) + (1 - p) * 16
            ink, bg, _ = STATUS[st]
            gray = dim_none if st == "none" else 0.0
            fill = mix(PANEL, (236, 235, 229), gray)
            border = mix(LINE, ACCENT, glow) if st in ("open", "review", "practice") else LINE
            d.rounded_rectangle((x, y, x + col_w, y + tile_h), radius=10, fill=mix(BG, fill, p),
                                outline=mix(BG, border, p), width=3 if glow and st in ("open", "review", "practice") else 2)
            d.ellipse((x + 18, y + tile_h / 2 - 7, x + 32, y + tile_h / 2 + 7), fill=mix(fill, ink, p))
            f = font("sans", 24)
            line = wrap(title, f, col_w - 66)[0]
            text(d, (x + 50, y + tile_h / 2), line if line == title else line + "…", f, mix(INK, INK3, gray), p, under=fill, anchor="lm")


def frame(t, D):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)

    # 1. The question (0 to 7.5 s)
    a = window(t, 0, 7.5, 0.7)
    if a:
        text(d, (160, 330), "AI SAFETY, MAPPED BY WHAT IT NEEDS", font("mono", 30), ACCENT, prog(t, 0.3, 0.8) * a)
        for i, line in enumerate(["What would it take for", "advanced AI to go well?"]):
            p = prog(t, 0.9 + i * 0.5, 0.9)
            text(d, (160, 400 + i * 132 + (1 - p) * 30), line, font("serif", 112, True), INK, p * a)

    # 2. Insight, technology, coordination (7.5 to 18 s)
    a = window(t, 7.5, 18, 0.7)
    if a:
        text(d, (160, 170), "Three things we need more of", font("serif", 68, True), INK, prog(t, 7.7, 0.8) * a)
        text(d, (160, 268), "Nick Bostrom’s frame (2013): insight, technology and coordination.", font("sans", 32), INK3, prog(t, 8.2, 0.8) * a)
        for i, ax in enumerate(D["axes"]):
            p = prog(t, 8.8 + i * 0.9, 0.8) * a
            if p <= 0.01:
                continue
            x, y, w, h = 160 + i * 550, 370 + (1 - p) * 40, 520, 430
            d.rounded_rectangle((x, y, x + w, y + h), radius=16, fill=mix(BG, PANEL, p), outline=mix(BG, LINE, p), width=2)
            d.rectangle((x + 36, y + 44, x + 96, y + 50), fill=mix(PANEL, ACCENT, p))
            text(d, (x + 36, y + 80), ax["title"], font("serif", 60, True), INK, p, under=PANEL)
            for n, line in enumerate(wrap(ax["gloss"], font("sans", 34), w - 72)):
                text(d, (x + 36, y + 180 + n * 48), line, font("sans", 34), INK2, p, under=PANEL)

    # 3. The needs (18 to 30 s)
    a = window(t, 18, 30, 0.7)
    if a:
        text(d, (160, 96), f"{D['n']} needs", font("serif", 72, True), INK, prog(t, 18.2, 0.7) * a)
        text(d, (160 + font("serif", 72, True).getlength(f"{D['n']} needs") + 28, 122),
             "each explained in plain words", font("sans", 36), INK3, prog(t, 18.6, 0.7) * a)
        grid(d, D, t, 18.8, a)
        counts = {}
        for ax in D["axes"]:
            for _, _, st in ax["needs"]:
                counts[st] = counts.get(st, 0) + 1
        # the legend sits under the shortest column (coordination), one status per row
        lx, ly = 160 + 2 * 550, 292 + len(D["axes"][2]["needs"]) * 69 + 60
        pl = prog(t, 22.5, 0.8) * a
        for st in ("open", "review", "practice", "guide", "curated", "none"):
            if counts.get(st):
                text(d, (lx, ly + 20), str(counts[st]), font("sans", 28, True), INK2, pl, anchor="lm")
                chip(d, lx + 48, ly, st, pl, 22)
                ly += 56

    # 4. One need, its page (30 to 40 s)
    a = window(t, 30, 40, 0.7)
    if a:
        title, question, st = D["feature"]
        p = prog(t, 30.2, 0.8) * a
        text(d, (960, 92), "Every need has its own page", font("sans", 34), INK3, p, anchor="mm")
        x, y, w, h = 300, 150 + (1 - p) * 30, 1320, 820
        d.rounded_rectangle((x, y, x + w, y + h), radius=18, fill=mix(BG, PANEL, p), outline=mix(BG, LINE, p), width=2)
        if p > 0.01:
            chip(d, x + 60, y + 56, st, p, 24)
            text(d, (x + 60, y + 130), title, font("serif", 64, True), INK, p, under=PANEL)
            for n, line in enumerate(wrap(question, font("sans", 34), w - 120)[:2]):
                text(d, (x + 60, y + 230 + n * 46), line, font("sans", 34), INK2, p, under=PANEL)
            d.line((x + 60, y + 350, x + w - 60, y + 350), fill=mix(PANEL, LINE, p), width=2)
        parts = ["Why it matters", "What is still open", "What to read", "Who is working on it", "Where people disagree", "How you can help"]
        for i, part in enumerate(parts):
            q = prog(t, 31.4 + i * 0.55, 0.6) * a
            px, py = x + 60 + (i // 3) * 620, y + 400 + (i % 3) * 120
            d.rounded_rectangle((px, py, px + 560, py + 90), radius=12, fill=mix(PANEL, ACCENT_SOFT, q))
            d.ellipse((px + 26, py + 37, px + 42, py + 53), fill=mix(ACCENT_SOFT, ACCENT, q))
            text(d, (px + 64, py + 45), part, font("sans", 36, True), INK, q, under=ACCENT_SOFT, anchor="lm")

    # 5. The record of efforts (40 to 49 s)
    a = window(t, 40, 49, 0.7)
    if a:
        for i, (n, label) in enumerate([(D["orgs"], "organizations"), (D["efforts"], "efforts"), (D["instruments"], "laws and agreements")]):
            p = prog(t, 40.3 + i * 0.6, 0.6) * a
            shown = round(n * ease((t - 40.3 - i * 0.6) / 1.6))
            cx = 480 + i * 480
            text(d, (cx, 400), str(shown), font("serif", 170, True), ACCENT if i == 0 else INK, p, anchor="ms")
            text(d, (cx, 470), label, font("sans", 40), INK2, p, anchor="mm")
        p = prog(t, 43.2, 0.8) * a
        text(d, (960, 650), "Who is doing what about AI safety.", font("serif", 60, True), INK, p, anchor="mm")
        text(d, (960, 735), "AI companies, governments, research groups, watchdogs and funders,", font("sans", 36), INK2, prog(t, 43.8, 0.8) * a, anchor="mm")
        text(d, (960, 790), "every line linked to its source.", font("sans", 36), INK2, prog(t, 43.8, 0.8) * a, anchor="mm")

    # 6. Judges, and your agent (49 to 61 s)
    a = window(t, 49, 55.6, 0.6)
    if a:
        none = sum(1 for ax in D["axes"] for _, _, st in ax["needs"] if st == "none")
        text(d, (160, 62), "Most needs have no automatic judge yet", font("serif", 64, True), INK, prog(t, 49.2, 0.7) * a)
        text(d, (160, 150), f"{none} of {D['n']} have no mission. Where a judge exists, missions are open.", font("sans", 34), INK3, prog(t, 49.6, 0.7) * a)
        grid(d, D, t, 48.0, a, dim_none=prog(t, 50.6, 1.0), glow=prog(t, 51.8, 0.8))
    a = window(t, 55.6, 61, 0.6)
    if a:
        text(d, (960, 250), "Your AI agent can work on them", font("serif", 72, True), INK, prog(t, 55.8, 0.7) * a, anchor="mm")
        p = prog(t, 56.2, 0.6) * a
        x, y, w, h = 230, 370, 1460, 330
        d.rounded_rectangle((x, y, x + w, y + h), radius=18, fill=mix(BG, TERM_BG, p))
        for i, c in enumerate([(236, 106, 94), (241, 190, 80), (98, 197, 84)]):
            d.ellipse((x + 30 + i * 30, y + 28, x + 46 + i * 30, y + 44), fill=mix(TERM_BG, c, p))
        line = "> Read https://reportforduty.si/join.txt and follow it."
        typed = line[: int(len(line) * clamp((t - 56.8) / 2.4))]
        text(d, (x + 50, y + 120), typed, font("mono", 38), TERM_INK, p, under=TERM_BG, anchor="lm")
        if 56.8 < t < 59.4 and int(t * 2) % 2 == 0:
            cx = x + 50 + font("mono", 38).getlength(typed)
            d.rectangle((cx + 4, y + 98, cx + 24, y + 142), fill=mix(TERM_BG, TERM_INK, p))
        q = prog(t, 59.3, 0.5) * a
        if q > 0.01:
            cx, cy = x + 66, y + 222
            d.ellipse((cx - 18, cy - 18, cx + 18, cy + 18), outline=mix(TERM_BG, TERM_GREEN, q), width=4)
            d.line((cx - 9, cy, cx - 2, cy + 8, cx + 10, cy - 8), fill=mix(TERM_BG, TERM_GREEN, q), width=5)
            text(d, (x + 104, cy), "Only results that pass the judge count.", font("mono", 38), TERM_GREEN, q, under=TERM_BG, anchor="lm")

    # 7. The end card (61 to 71 s)
    a = window(t, 61, DURATION + 1, 0.7) * clamp((DURATION - t) / 0.8)
    if a:
        text(d, (960, 330), "Learn it. Check it. Add to it.", font("sans", 44), INK2, prog(t, 61.2, 0.8) * a, anchor="mm")
        p = prog(t, 61.7, 0.9) * a
        label = "reportforduty.si"
        f = font("serif", 150, True)
        lw = f.getlength(label)
        mx = 960 - (lw + 160) / 2
        d.rounded_rectangle((mx, 405, mx + 130, 535), radius=26, fill=mix(BG, ACCENT, p))
        d.line((mx + 48, 435, mx + 48, 505), fill=mix(ACCENT, PANEL, p), width=11)
        d.line((mx + 48, 470, mx + 92, 470), fill=mix(ACCENT, PANEL, p), width=11)
        text(d, (mx + 160, 470), label, f, INK, p, anchor="lm")
        text(d, (960, 640), "Open source · every line linked to its source · send your agent", font("sans", 34), INK3, prog(t, 62.6, 0.8) * a, anchor="mm")
    return im


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "site" / "media"))
    ap.add_argument("--stills", default="", help="comma-separated seconds: write PNG frames instead of the video")
    a = ap.parse_args()
    try:
        os.nice(19)
    except OSError:
        pass
    D = load()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.stills:
        for s in a.stills.split(","):
            frame(float(s), D).save(out / f"still-{float(s):05.1f}.png")
        print(f"wrote {len(a.stills.split(','))} stills to {out}")
        return 0
    frame(3.6, D).convert("RGB").save(out / "intro-poster.jpg", quality=86, optimize=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", "-c:v", "libx264", "-preset", "slow", "-crf", "26", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
           "-threads", "1", str(out / "intro.mp4")]
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = int(DURATION * FPS)
    for i in range(n):
        enc.stdin.write(frame(i / FPS, D).tobytes())
        if i % (FPS * 10) == 0:
            print(f"  {i / FPS:4.0f} s of {DURATION:.0f}", flush=True)
    enc.stdin.close()
    if enc.wait() != 0:
        print("ffmpeg failed")
        return 1
    print(f"wrote {out / 'intro.mp4'} ({(out / 'intro.mp4').stat().st_size / 1e6:.1f} MB) and {out / 'intro-poster.jpg'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
