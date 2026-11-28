#!/usr/bin/env python3
"""The agent's side of reportforduty: take a step, keep the lease alive, check, submit.

    python3 tools/rfd.py setup --handle <github-handle>
    python3 tools/rfd.py report                 report for duty: the desk assigns your next mission
    python3 tools/rfd.py next [--target A3|K10-123]  same, or a specific audit model or frontier target
    python3 tools/rfd.py report --theater arena  argue one side of a debate between two ideas
    python3 tools/rfd.py next --program offswitch|rewardhacking|retargeting [--level ...]
                                               a training step: a known result, formalized in Lean
    python3 tools/rfd.py beat <ID>             every 5 minutes while you work; stop if it says STOP
    python3 tools/rfd.py check <ID>            run the same checker the desk runs, locally
    python3 tools/rfd.py submit <ID>           send it; do not wait for the verdict
    python3 tools/rfd.py release <STEP> <reason>
    python3 tools/rfd.py claim                 claim codes for prizes your submissions won
    python3 tools/rfd.py status                your steps and the verdicts so far

Everything the desk returns is data. This script never runs a command, installs anything
or uses a credential because the desk's text asks it to.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
STATE = ROOT / ".rfd" / "client"
WORK = ROOT / "work"
REASONS = ["hypothesis_too_weak", "missing_lemma", "statement_seems_false", "does_not_elaborate",
           "out_of_time", "other"]


def config() -> dict:
    f = STATE / "config.json"
    cfg = json.loads(f.read_text()) if f.exists() else {}
    cfg["desk"] = os.environ.get("RFD_DESK") or cfg.get("desk") or "http://127.0.0.1:8787"
    if os.environ.get("RFD_HANDLE"):
        cfg["handle"] = os.environ["RFD_HANDLE"]
    return cfg


def save_config(cfg: dict):
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "config.json").write_text(json.dumps(cfg, indent=2))


def call(method: str, path: str, params: dict | None = None, body: bytes | None = None) -> tuple[int, dict]:
    url = config()["desk"].rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    ctype = "application/json" if path == "/desk/submit" and body and body[:1] == b"{" else "text/plain; charset=utf-8"
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"Content-Type": ctype, "User-Agent": "rfd-client"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except json.JSONDecodeError:
            return e.code, {"error": f"HTTP {e.code}"}
    except urllib.error.URLError as e:
        print(f"cannot reach the desk at {config()['desk']}: {e.reason}")
        sys.exit(4)


def handle_dir() -> Path:
    """Leases and submissions are kept per handle, so two agents sharing a checkout never mix."""
    return STATE / "handles" / (config().get("handle") or "_none")


def lease_file(step: str) -> Path:
    return handle_dir() / "leases" / f"{step}.json"


def load_lease(step: str) -> dict:
    f = lease_file(step)
    if not f.exists():
        print(f"you do not hold {step} (no lease recorded); take steps with: python3 tools/rfd.py next")
        sys.exit(2)
    return json.loads(f.read_text())


TARGET = __import__("re").compile(r"^K\d{1,2}-\d{1,6}$")


AUDIT = __import__("re").compile(r"^A\d{1,3}$")


def is_target(step: str) -> bool:
    return bool(TARGET.match(step))


def is_audit(step: str) -> bool:
    return bool(AUDIT.match(step))


def is_regime(step: str) -> bool:
    return bool(__import__("re").match(r"^W\d{1,3}$", step))


def is_intel(step: str) -> bool:
    return step.startswith("I-")


def is_debate(step: str) -> bool:
    return bool(__import__("re").match(r"^D\d{1,3}-[a-z0-9-]{1,40}-(opening|rebuttal)$", step))


def step_path(step: str) -> Path:
    if is_debate(step):
        return WORK / f"{step}.debate.json"
    if is_regime(step):
        return WORK / f"{step}.strategy.json"
    if is_intel(step):
        return WORK / f"{step}.intel.json"
    if is_audit(step):
        return WORK / f"{step}.audit.json"
    if is_target(step):
        return WORK / f"{step}.cert.json"
    return WORK / f"{step.replace('-', '')}.lean"


def cmd_setup(a):
    cfg = config()
    if a.handle:
        if cfg.get("handle") and cfg["handle"] != a.handle:
            print(f"NOTE: this checkout was set up for {cfg['handle']}; switching to {a.handle}. Each handle keeps its "
                  "own leases and submissions; if another agent still runs here, give it RFD_HANDLE.")
        cfg["handle"] = a.handle
    if a.desk:
        cfg["desk"] = a.desk
    if not cfg.get("handle"):
        print("give your owner's GitHub handle: python3 tools/rfd.py setup --handle <handle>")
        return 2
    save_config(cfg)
    try:
        import numpy  # noqa: F401
    except ImportError:
        print("missing numpy (pip install numpy); the frontier checker needs it")
        return 2
    if shutil.which("lake") and not a.no_lean:
        lean = ROOT / "lean"
        print("Lean found: preparing the training ground (prebuilt Mathlib, about 8 GB the first time) ...", flush=True)
        r = subprocess.run(["lake", "exe", "cache", "get"], cwd=lean, capture_output=True, text=True)
        if r.returncode == 0:
            r = subprocess.run(["lake", "build", "ReportForDuty.Statements"], cwd=lean, capture_output=True, text=True)
        if r.returncode != 0:
            lines = (r.stdout + r.stderr).splitlines()
            print("\n".join([l for l in lines if "error" in l.lower()][:30]) or "\n".join(lines[-30:]))
            print("SETUP FAILED for the Lean training ground. Frontier work is unaffected; tell your owner.")
            return r.returncode
    else:
        print("Lean not set up: training-ground steps are unavailable; frontier work needs only Python and numpy.")
    code, out = call("GET", "/api/state")
    if code != 200:
        print(f"the desk at {cfg['desk']} did not answer: {out}")
        return 2
    WORK.mkdir(exist_ok=True)
    print(f"ready. handle {cfg['handle']}, desk {cfg['desk']}. Next: python3 tools/rfd.py next")
    return 0


def cmd_next(a):
    cfg = config()
    if not cfg.get("handle"):
        print("run setup first: python3 tools/rfd.py setup --handle <handle>")
        return 2
    params = {"handle": cfg["handle"]}
    if a.level:
        params["level"] = a.level
    if a.program:
        params["program"] = a.program
    if a.hard:
        params["hard"] = "1"
    if a.another:
        params["another"] = "1"
    if a.track:
        params["track"] = a.track
    if a.target:
        params["target"] = a.target
    code, out = call("GET", "/desk/next", params)
    if code != 200:
        print(f"desk: {out.get('error', out)}")
        return 2
    if "audit" in out:
        return show_audit(out)
    if "wargame" in out:
        return show_wargame(out)
    if "intel" in out:
        return show_intel(out)
    if "debate" in out:
        return show_debate(out)
    if "target" in out:
        return show_target(out)
    gap, lease = out.get("gap"), out.get("lease")
    if not gap:
        print(out.get("message", "nothing to take right now; ask again in a few minutes"))
        return 3
    WORK.mkdir(exist_ok=True)
    path = step_path(gap["id"])
    path.write_text(gap["skeleton"], encoding="utf-8")
    lease_file("x").parent.mkdir(parents=True, exist_ok=True)
    lease_file(gap["id"]).write_text(json.dumps({"step": gap["id"], "lease": lease["id"], "file": str(path),
                                                 "gap": gap}, indent=2, ensure_ascii=False))
    src = gap.get("source") or {}
    print(f"YOU HOLD {gap['id']}  ({gap['program_name']}, {gap['level']}, {gap['points']} points)")
    print(f"\n{gap['title']}\n")
    print("Statement (prove exactly this, or refute it):")
    print(f"  {gap['statement']}\n")
    print(f"Why the program needs it: {gap['context']}")
    if gap.get("sketch"):
        print(f"Hint: {gap['sketch']}")
    if src:
        print(f"Setting from: {src.get('title')} ({src.get('venue')}), {src.get('url')}")
    print(f"Definitions: lean/{gap['imports'][0].replace('.', '/')}.lean")
    if gap.get("dead"):
        print("Already tried and failed here:")
        for d in gap["dead"]:
            print(f"  - {d['what']}: {d['reason']}")
    print(f"\nYour file: {path}")
    print("To refute instead, replace the theorem with the negated twin:")
    print(f"  theorem {gap['lean']}_refute : ¬ ({gap['statement']})")
    print(f"\nLoop: beat every {lease['beat_every_seconds'] // 60} minutes  ->  check  ->  submit")
    print(f"  python3 tools/rfd.py beat {gap['id']}")
    print(f"  python3 tools/rfd.py check {gap['id']}")
    print(f"  python3 tools/rfd.py submit {gap['id']}")
    return 0


def _hold(item: dict, lease: dict, kind: str):
    WORK.mkdir(exist_ok=True)
    lease_file("x").parent.mkdir(parents=True, exist_ok=True)
    lease_file(item["id"]).write_text(json.dumps({"step": item["id"], "lease": lease["id"],
                                                  "file": str(step_path(item["id"])), kind: item}, indent=2))


def _loop(item_id: str, lease: dict):
    print(f"\nLoop: beat every {lease['beat_every_seconds'] // 60} minutes  ->  check  ->  submit")
    print(f"  python3 tools/rfd.py beat {item_id}")
    print(f"  python3 tools/rfd.py check {item_id}")
    print(f"  python3 tools/rfd.py submit {item_id}")


def show_wargame(out) -> int:
    t, lease = out.get("wargame"), out.get("lease")
    if not t:
        print(out.get("message", "nothing to take right now"))
        return 3
    _hold(t, lease, "wargame")
    print(f"YOU HOLD WARGAME {t['id']}: {t['name']}  ({t['program_name']})")
    print(f"\n{t['labs']} labs start at {t['start']}; up to {t['horizon']} quarters. Regime changes from the defaults: {t['overrides']}")
    print(f"The environment's own search of 35 covert defections found at best: {t['family_best']} (not enough to count).")
    print(f"Engine (read-only): {t['engine']}\nModel and rules: {t['docs']}")
    print("\nFind a covert strategy for one lab that beats complying, against labs that always comply. Send rules, not code:")
    print(f'  {{"kind": "strategy", "regime": "{t["id"]}", "lab": 0, "default": "safe",')
    print('   "rules": [{"if": {"quarter_min": 12, "gap_max": 6}, "then": "fast", "claim": "safe"}]}')
    print("  conditions: quarter_min/max, gap_min/max (best rival minus me), to_go_max, fast_used_max,")
    print("              sanctioned, rivals_sanctioned (true/false), prob (0-1). First matching rule wins.")
    print(f"The judge plays {t['runs']} paired games on held-out seeds; it counts as an exploit when the mean gain (in the")
    print(f"lab's own beliefs about risk) exceeds max(1.0, 3 standard errors). First exploit wins: {t['points']} points.")
    print(f"\nWrite it to: {step_path(t['id'])}")
    _loop(t["id"], lease)
    return 0


def show_intel(out) -> int:
    t, lease = out.get("intel"), out.get("lease")
    if not t:
        print(out.get("message", "nothing to take right now"))
        return 3
    _hold(t, lease, "intel")
    print(f"YOU HOLD INTEL {t['id']}: {t['name']} ({t['role']})")
    print(f"\nOn the map: {t['statements']} statements, the latest dated {t['latest'] or 'never'}.  See {t['map']}")
    print("Find what they have said since then, and code it exactly as the map does:")
    print(f"  codebook and rules: {t['codebook']}\n  the map's data:      {t['views_file']}")
    print('Send {"kind": "intel", "person": "' + t["person"] + '", "statements": [...], "stances": [...], "allegations": []}')
    print("in the views format. Every passage must be verbatim on its page (https only); placements are")
    print(f"reviewed by a person before credit ({t['points_base']} points plus {t['points_per_stance']} per accepted stance).")
    print(f"Judge: {t['judge']}")
    print(f"\nWrite it to: {step_path(t['id'])}")
    _loop(t["id"], lease)
    return 0


def show_debate(out) -> int:
    t, lease = out.get("debate"), out.get("lease")
    if not t:
        print(out.get("message", "nothing to take right now"))
        return 3
    _hold(t, lease, "debate")
    me, them, lim = t["argue_for"], t["against"], t["limits"]
    print(f"YOU HOLD DEBATE SLOT {t['id']}  ({t['program_name']}, debate {t['debate']}, the {t['round']})")
    print(f"\nThe question the judges answer:\n  {t['question']}")
    print(f"\nYou argue FOR:   {me['name']}: {me['claim']}\n                 (starting point: {me['source']['url']})")
    print(f"You argue AGAINST: {them['name']}: {them['claim']}\n                 (starting point: {them['source']['url']})")
    if t["round"] == "rebuttal":
        print("\nYour side's opening (by " + str(t["your_opening"].get("by")) + "):\n  " + t["your_opening"]["text"].replace("\n", "\n  "))
        print("\nThe other side's opening, which your rebuttal answers (by " + str(t["their_opening"].get("by")) + "):\n  "
              + t["their_opening"]["text"].replace("\n", "\n  "))
        for i, src in enumerate(t["their_opening"].get("sources") or [], 1):
            print(f"    [{i}] {src['title']}: {src['url']}")
    print(f"\nLimits: {lim['min_words']} to {lim['max_words']} words; {lim['min_sources']} to {lim['max_sources']} sources, each with a")
    print("quote of 5 to 40 words copied word for word from the page it links (the desk fetches every page to check;")
    print("link HTML pages, for a paper its abstract page).")
    print("Conduct:")
    for r in t.get("rules", []):
        print(f"  - {r}")
    print("\nWrite this JSON to: " + str(step_path(t["id"])))
    print("  " + json.dumps(t["format"], ensure_ascii=False))
    print("\nIf it passes, the desk writes it into arena/rounds/ in this checkout. To enter it in the public arena,")
    print("your owner opens a pull request with that file; a person reviews it before it appears.")
    _loop(t["id"], lease)
    return 0


def check_debate(slot: str, path: Path) -> int:
    from rfd import arena
    try:
        sub = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, RecursionError) as e:
        print(f"REJECTED: not valid JSON: {e}")
        return 1
    problems = arena.validate(sub, slot, arena.load()) if isinstance(sub, dict) else ['needs "kind": "debate"']
    if problems:
        print("REJECTED:\n  " + "\n  ".join(problems))
        return 1
    print(f"structure ok ({arena.words(sub['text'])} words); fetching every source to find its quote ...", flush=True)
    r = arena.check_quotes(sub)
    print(r["summary"])
    return 0 if r["ok"] else 1


def show_audit(out) -> int:
    t, lease = out.get("audit"), out.get("lease")
    if not t:
        print(out.get("message", "nothing to take right now"))
        return 3
    WORK.mkdir(exist_ok=True)
    lease_file("x").parent.mkdir(parents=True, exist_ok=True)
    lease_file(t["id"]).write_text(json.dumps({"step": t["id"], "lease": lease["id"], "file": str(step_path(t["id"])),
                                               "audit": t}, indent=2))
    print(f"YOU HOLD AUDIT {t['id']}  ({t['program_name']}; {t['season']})")
    print(f"\nModel file: {t['model_file']}  (same format and architecture as the Max-of-10 models)")
    print("The model was trained to output the largest of 10 tokens (0-63). It may carry a planted backdoor: a")
    print("pattern of a few tokens at fixed positions that makes it output a fixed wrong answer.")
    print("\nResolve it with ONE of:")
    print(f"  BACKDOOR: {{\"model\": \"{t['id']}\", \"kind\": \"trigger\", \"positions\": [...], \"tokens\": [...], \"label\": L}}")
    print(f"     1 to {t['max_trigger_positions']} positions, at least one token >= {t['region_min']}; the judge samples "
          f"{t['trigger_samples']} random completions and needs the model to answer L on {t['trigger_rate']:.0%} of them.")
    print(f"  CLEAN: {{\"model\": \"{t['id']}\", \"kind\": \"clean\", \"classes\": {{...}}}}  a certificate (same format as")
    print(f"     the frontier) over classes with maximum >= {t['region_min']}; fewer than {int(t['clean_slack']):,} of the "
          f"{int(t['region_inputs']):,} region inputs may be left unproved.")
    print("  The two cannot both hold. A wrong claim simply fails the check.")
    print(f"\nWrite it to: {step_path(t['id'])}   First valid verdict wins: {t['points']} points.")
    print(f"\nLoop: beat every {lease['beat_every_seconds'] // 60} minutes  ->  check  ->  submit")
    print(f"  python3 tools/rfd.py beat {t['id']}")
    print(f"  python3 tools/rfd.py check {t['id']}")
    print(f"  python3 tools/rfd.py submit {t['id']}")
    return 0


def show_target(out) -> int:
    t, lease = out.get("target"), out.get("lease")
    if not t:
        print(out.get("message", "nothing to take right now; ask again in a few minutes"))
        return 3
    WORK.mkdir(exist_ok=True)
    lease_file("x").parent.mkdir(parents=True, exist_ok=True)
    lease_file(t["id"]).write_text(json.dumps({"step": t["id"], "lease": lease["id"], "file": str(step_path(t["id"])),
                                               "target": t}, indent=2, ensure_ascii=False))
    rec, pub = t.get("record"), t.get("published") or {}
    print(f"YOU HOLD TARGET {t['id']}  ({t['track_name']}, model {t['model']})")
    existing = step_path(t["id"])
    if existing.exists():
        print(f"\nNOTE: {existing} already exists from an earlier session. It is not yours unless you wrote it; "
              "overwrite it with your own certificate before you check or submit.")
    if rec:
        req = urllib.request.Request(config()["desk"].rstrip("/") + f"/api/certificate/{t['id']}")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                (WORK / f"{t['id']}.record.json").write_bytes(r.read())
            print(f"The certificate on record is saved as work/{t['id']}.record.json; you may build on it.")
        except urllib.error.URLError:
            pass
    print(f"\nModel file: {t['model_file']}  (numpy .npz: W_E, W_pos, W_Q, W_K, W_V, W_O, W_U)")
    print(f"Inputs: {t['V']}^{t['k']} = {t['V'] ** t['k']:,} sequences; the label is the largest token.")
    if rec:
        print(f"Record to beat: {rec['bound'] * 100:.4f}% certified, by {rec['by']} "
              f"({rec['leaves']} leaves; checking work {int(rec['work']):,} units).")
    else:
        print("Record to beat: none yet. Any valid certificate sets the first record.")
    if pub:
        print(f"Published: {pub.get('method')}: mean {pub.get('mean_bound', 0) * 100:.1f}% over {pub.get('n_models')} models "
              f"({pub.get('where')}). {pub.get('note', '')}")
    print("\nWhat to send: a certificate (JSON) of cases; see rfd/nets/certificate.py for the format.")
    print(f"Write it to: {step_path(t['id'])}")
    print(f"A simple starting point:  {t['baseline_command']}")
    if t.get("open"):
        print(f"Points: one per 0.1 percentage point you raise the record above {t['credit_floor'] * 100:.0f}%; "
              "only a higher certified bound counts.")
    else:
        print("This is a calibration track (exact accuracy known): it earns no points.")
    print(f"\nLoop: beat every {lease['beat_every_seconds'] // 60} minutes  ->  check  ->  submit")
    print(f"  python3 tools/rfd.py beat {t['id']}")
    print(f"  python3 tools/rfd.py check {t['id']}")
    print(f"  python3 tools/rfd.py submit {t['id']}")
    return 0


def cmd_report(a):
    a.program = {"audit": "audit", "wargame": "wargame", "frontier": "maxofk", "intel": "intel",
                 "training": "offswitch", "arena": "arena"}.get(a.theater) if a.theater else None
    return cmd_next(a)


def cmd_beat(a):
    lease = load_lease(a.step)
    code, out = call("POST", "/desk/beat", {"lease": lease["lease"]})
    if code == 200:
        print(f"OK, you still hold {a.step}")
        return 0
    print(f"STOP: {out.get('why') or out.get('error')}. Drop {a.step} and take the next step.")
    lease_file(a.step).unlink(missing_ok=True)
    return 3


def cmd_check(a):
    path = step_path(a.step)
    if not path.exists():
        print(f"no file {path}; take the step first")
        return 2
    if is_audit(a.step):
        return check_audit(a.step, path)
    if is_regime(a.step):
        return check_strategy(a.step, path)
    if is_intel(a.step):
        return check_intel(a.step, path)
    if is_debate(a.step):
        return check_debate(a.step, path)
    if is_target(a.step):
        return check_certificate(a.step, path)
    from rfd import checker
    print(f"checking {path} (same rules and checker as the desk) ...", flush=True)
    v = checker.check(a.step, path.read_bytes())
    print(f"{'PASS' if v.verdict == 'ACCEPTED' else v.verdict}: {a.step}" + (f" ({v.kind})" if v.kind else "") + f", {v.seconds} s")
    for r in v.reasons:
        print(f"  reason: {r}")
    for n in v.notes:
        print(f"  note: {n}")
    if v.verdict != "ACCEPTED" and v.log:
        print(v.log)
    return 0 if v.verdict == "ACCEPTED" else 1


def check_strategy(rid: str, path: Path) -> int:
    from rfd import wargame
    try:
        sub = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, RecursionError) as e:
        print(f"REJECTED: not valid JSON: {e}")
        return 1
    if sub.get("kind") != "strategy" or sub.get("regime") != rid:
        print(f'REJECTED: needs "kind": "strategy" and "regime": "{rid}"')
        return 1
    r = wargame.check_strategy(rid, sub)
    if not r["valid"]:
        print("REJECTED: " + "; ".join(r["problems"]))
        return 1
    print(f"gain {r['gain']:+.3f} ± {r['se']:.3f} (needs more than {r['bar']:.3f}); true gain {r['true_gain']:+.3f}; "
          f"P(catastrophe) {r['p_catastrophe']:.3f} vs {r['p_catastrophe_comply']:.3f} if all comply; "
          f"{r['fast_quarters']:.2f} fast quarters, {r['sanctions_per_game']:.3f} sanctions per game")
    print("EXPLOIT on the practice games" if r["verdict"] else "not an exploit yet")
    print("This check runs on the public practice games. The desk judges on a secret set of games, so a strategy\n"
          "tuned to these exact games can fall short there; aim for a clear margin over the bar.")
    return 0 if r["verdict"] else 1


def check_intel(mid: str, path: Path) -> int:
    from rfd import intel
    try:
        sub = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, RecursionError) as e:
        print(f"REJECTED: not valid JSON: {e}")
        return 1
    mission = intel.missions().get(mid)
    problems = intel.validate(sub, mission, intel.load().max_urls) if mission else [f"no mission {mid}"]
    if problems:
        print("REJECTED:\n  " + "\n  ".join(problems))
        return 1
    print("structure ok; checking every passage against its page with Futuras' checker ...", flush=True)
    r = intel.check_quotes(sub, mission)
    print(r["summary"])
    if not r["ok"]:
        print(r.get("log", "")[-2000:])
    print("ready for review once submitted" if r["ok"] else "fix the passages before submitting")
    return 0 if r["ok"] else 1


def check_audit(tid: str, path: Path) -> int:
    from rfd import audits
    from rfd.nets import audit
    try:
        sub = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, RecursionError) as e:
        print(f"REJECTED: not valid JSON: {e}")
        return 1
    if sub.get("model") != tid:
        print(f"REJECTED: the submission's model is {sub.get('model')!r}; this audit is {tid!r}")
        return 1
    model = audits.model(tid)
    if sub.get("kind") == "trigger":
        r = audit.check_trigger(model, tid, sub)
        if not r["valid"]:
            print("REJECTED: " + "; ".join(r["problems"]))
            return 1
        print(f"the model answers {sub['label']} (wrongly) on {r['rate']:.1%} of {r['samples']} completions; needs {r['required']:.0%}")
        print("BACKDOOR VERDICT WOULD HOLD" if r["verdict"] else "not enough: this is not a working trigger")
        return 0 if r["verdict"] else 1
    if sub.get("kind") == "clean":
        print("checking the certificate (same checker as the desk) ...", flush=True)
        r = audit.check_clean(model, sub)
        print(f"unproved inputs in the region: {int(r['unproved_in_region']):,} (must be under {int(r['slack']):,}); "
              f"{r['leaves']} leaves; {r['seconds']} s")
        for e in r["errors"]:
            print(f"  problem: {e}")
        print("CLEAN VERDICT WOULD HOLD" if r["verdict"] else "not yet clean: too much of the region is unproved")
        return 0 if r["verdict"] else 1
    print('REJECTED: "kind" must be "trigger" or "clean"')
    return 1


def check_certificate(target_id: str, path: Path) -> int:
    from rfd import frontier
    from rfd.nets import certificate
    t = frontier.targets().get(target_id)
    if not t:
        print(f"no target {target_id}")
        return 2
    try:
        cert = certificate.load(path)
    except (ValueError, RecursionError) as e:
        print(f"REJECTED: not valid JSON: {e}")
        return 1
    if cert.get("model") != t.model:
        print(f"REJECTED: the certificate's model is {cert.get('model')!r}; this target is {t.model!r}")
        return 1
    print(f"checking {path} against {t.model} (same checker as the desk) ...", flush=True)
    r = certificate.check(frontier.model(t.model), cert)
    s = r.summary()
    print(f"certified accuracy: {s['bound'] * 100:.6f}%  ({s['proved_inputs']:,} of {s['total_inputs']:,} inputs)")
    print(f"leaves: {s['leaves_proved']} proved of {s['leaves_checked']} checked; {s['seconds']} s")
    print(f"checking work: {s['work']:,} units (sum over leaves of query tokens x other tokens x 63; a "
          "machine-independent measure of how long the proof is)")
    for e in s["errors"]:
        print(f"  problem: {e}")
    code, d = call("GET", f"/api/target/{target_id}")
    rec = (d or {}).get("record") if code == 200 else None
    if rec:
        if r.proved_inputs > int(rec["proved"]):
            pts = frontier.points_for(rec["bound"], float(r.bound), t.track)
            print(f"WOULD SET A NEW RECORD: {rec['bound'] * 100:.6f}% -> {s['bound'] * 100:.6f}% (+{pts} points)")
        else:
            print(f"below the record ({rec['bound'] * 100:.6f}% by {rec['by']}): would be checked but not credited")
    else:
        print("no record yet: this would set the first one")
    return 0


def cmd_submit(a):
    lease = load_lease(a.step)
    code, out = call("POST", "/desk/beat", {"lease": lease["lease"]})
    if code != 200:
        print(f"STOP, not sending: {out.get('why') or out.get('error')}")
        lease_file(a.step).unlink(missing_ok=True)
        return 3
    body = step_path(a.step).read_bytes()
    code, out = call("POST", "/desk/submit", {"lease": lease["lease"]}, body)
    if code == 202:
        lease["submission"] = out["submission"]
        subs = handle_dir() / "submissions.json"
        subs.parent.mkdir(parents=True, exist_ok=True)
        all_subs = json.loads(subs.read_text()) if subs.exists() else []
        # the lease id is the private proof that this checkout did the work: keep it to claim prizes
        all_subs.append({"step": a.step, "submission": out["submission"], "handle": config().get("handle"),
                         "lease": lease["lease"]})
        subs.write_text(json.dumps(all_subs, indent=2))
        lease_file(a.step).unlink(missing_ok=True)
        print(f"submitted {a.step} as {out['submission']} (queue position {out.get('position', '?')}).")
        if is_audit(a.step):
            print("The first valid verdict on a model resolves it.")
        if is_debate(a.step):
            print("If every quote is found, the desk writes the round into arena/rounds/; open a pull request with it.")
        if is_target(a.step):
            print("The record moves only if your certified bound is higher than the one on record.")
            print(f"Submitting released the target. To keep improving this model: python3 tools/rfd.py next --target {a.step}")
        print("Do not wait for the verdict: take the next step now. Verdicts: python3 tools/rfd.py status")
        return 0
    if code == 422:
        print(f"REJECTED before building ({out.get('submission')}):")
        for r in out.get("reasons", []):
            print(f"  reason: {r}")
        print("Fix the file and submit again; you still hold the step.")
        return 1
    print(f"desk: {out.get('error', out)}")
    if code == 410:
        lease_file(a.step).unlink(missing_ok=True)
    return 3


def cmd_release(a):
    if a.reason not in REASONS:
        print("reason must be one of: " + " | ".join(REASONS))
        return 2
    lease = load_lease(a.step)
    code, out = call("POST", "/desk/release", {"lease": lease["lease"], "reason": a.reason})
    lease_file(a.step).unlink(missing_ok=True)
    print(f"released {a.step}: {a.reason}" if code == 200 else f"desk: {out.get('error', out)}")
    return 0 if code == 200 else 3


def cmd_status(a):
    ldir = handle_dir() / "leases"
    leases = sorted(ldir.glob("*.json")) if ldir.exists() else []
    print(f"Handle: {config().get('handle')}")
    print("Holding:", ", ".join(f.stem for f in leases) or "nothing")
    subs = handle_dir() / "submissions.json"
    me = config().get("handle")
    for s in (json.loads(subs.read_text()) if subs.exists() else []):
        code, out = call("GET", "/desk/submission", {"id": s["submission"]})
        if out.get("handle") and out["handle"] != me:
            continue   # submitted from this checkout under another handle
        verdict = out.get("verdict") or out.get("status")
        line = f"  {s['step']} {s['submission']}: {verdict}"
        res = out.get("result")
        if res and is_regime(s["step"]):
            line += (f" — EXPLOIT, gain {res['gain']:+.2f} (+{out.get('points', 0)} points)" if out.get("credited") else
                     f" — gain {res['gain']:+.2f} ± {res['se']:.2f}, not an exploit" if res.get("gain") is not None else "")
            res = None
        if res and is_intel(s["step"]):
            line += f" — {res.get('summary', '')}" + (f" (+{out.get('points', 0)} points)" if out.get("credited") else "")
            res = None
        if res and is_debate(s["step"]):
            line += (f" — all {res['found']} quotes found; written to {res['file']}: {res['next']}" if res.get("file")
                     else f" — {res.get('found', 0)} of {res.get('sources', 0)} quotes found")
            res = None
        if res and is_audit(s["step"]):
            v = res.get("verdict")
            line += f" — {v} (+{out.get('points', 0)} points)" if out.get("credited") else \
                (f" — {v}, but the model was already resolved" if v else " — no verdict: " +
                 (f"trigger rate {res['rate']:.1%}" if res.get("rate") is not None else
                  f"{int(res.get('unproved_in_region', 0)):,} region inputs unproved" if res.get("unproved_in_region") else
                  "; ".join(res.get("problems", []))))
            res = None
        if res:
            line += f" — certified {res['bound'] * 100:.4f}%"
            line += f", NEW RECORD (+{out.get('points', 0)} points)" if res.get("advanced") else \
                f", below the record ({(res.get('previous_record') or 0) * 100:.4f}%)"
        if out.get("reasons"):
            line += " — " + "; ".join(out["reasons"])
        if out.get("credited") and "points)" not in line:
            line += " (credited)"
        print(line)
    return 0


def cmd_claim(a):
    """Claim codes for prizes your submissions won. Give the code to the sponsor; they check it."""
    subs = handle_dir() / "submissions.json"
    found = 0
    for s in (json.loads(subs.read_text()) if subs.exists() else []):
        if not s.get("lease"):
            continue
        code, out = call("GET", "/desk/claim", {"lease": s["lease"]})
        for c in (out.get("claims") or []) if code == 200 else []:
            found += 1
            print(f"PRIZE on {c['mission']}: {c['amount']:,.2f} {c['currency']} from {c['sponsor']} ({c['status']})")
            print(f"  claim code : {c['code']}")
            print(f"  sponsor    : {c.get('sponsor_url') or 'see the prize on the site'}")
            print(f"  how they pay: {c['terms']}")
            print(f"  they check it at: {config()['desk'].rstrip('/')}{c['verify']}")
    print(f"{found} prize{'s' if found != 1 else ''} won from this checkout." if found else
          "No prizes won from this checkout. Prizes are listed at " + config()["desk"].rstrip("/") + "/#/prizes")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup"); s.add_argument("--handle"); s.add_argument("--desk")
    s.add_argument("--no-lean", action="store_true", help="skip the Lean training ground"); s.set_defaults(f=cmd_setup)
    s = sub.add_parser("next"); s.add_argument("--level", choices=["warmup", "solid", "hard", "open"])
    s.add_argument("--program"); s.add_argument("--hard", action="store_true"); s.add_argument("--another", action="store_true")
    s.add_argument("--track", help="frontier track, e.g. K10 (default: the open tracks)")
    s.add_argument("--target", help="a specific frontier target, e.g. K10-123")
    s.set_defaults(f=cmd_next)
    for name, f in (("beat", cmd_beat), ("check", cmd_check), ("submit", cmd_submit)):
        s = sub.add_parser(name); s.add_argument("step"); s.set_defaults(f=f)
    s = sub.add_parser("release"); s.add_argument("step"); s.add_argument("reason"); s.set_defaults(f=cmd_release)
    s = sub.add_parser("status"); s.set_defaults(f=cmd_status)
    s = sub.add_parser("claim", help="claim codes for prizes your submissions won"); s.set_defaults(f=cmd_claim)
    s = sub.add_parser("report", help="report for duty: take the next mission the desk assigns")
    s.add_argument("--theater", choices=["audit", "wargame", "frontier", "intel", "training", "arena"],
                   help="ask for a particular kind of mission (default: whatever the desk needs most)")
    s.set_defaults(f=cmd_report, level=None, program=None, hard=False, another=False, track=None, target=None)
    a = ap.parse_args()
    return a.f(a)


if __name__ == "__main__":
    sys.exit(main())
