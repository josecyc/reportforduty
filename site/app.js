"use strict";
/* Report for Duty: renders the desk's live data. All text from the desk is inserted as
   text nodes, never as HTML. */

const REASONS = {
  hypothesis_too_weak: "the hypotheses look too weak",
  missing_lemma: "a missing lemma",
  statement_seems_false: "the statement seems false",
  does_not_elaborate: "the statement does not compile",
  out_of_time: "out of time",
  other: "other",
  submitted: "submitted",
};
const STATUS_WORD = { proved: "Proved", refuted: "Refuted", checking: "Checking", in_work: "In work", open: "Available" };
const pct = (x, d = 2) => (x === null || x === undefined ? "—" : `${(x * 100).toFixed(d)}%`);
const isTarget = (id) => /^K\d{1,2}-\d+$/.test(id || "");
const isAudit = (id) => /^A\d{1,3}$/.test(id || "");
const isRegime = (id) => /^W\d{1,3}$/.test(id || "");
const isIntel = (id) => /^I-/.test(id || "");
const missionHref = (id) => isTarget(id) ? `#/target/${id}` : isAudit(id) ? `#/audit/${id}` :
  isRegime(id) ? `#/wargame/${id}` : isIntel(id) ? `#/intel` : `#/step/${id}`;
const LEVEL_ORDER = ["warmup", "solid", "hard", "open"];

let STATE = null;
let FEED = null;
let MAP = null;          /* site/map.json: the needs, texts, argument and lingo */
let VIEWS = undefined;   /* /api/views: Futuras' placements; null when Futuras is not available */
let EFFORTS = undefined; /* site/efforts.json: who is doing what; null when missing */
let PROGRAMS = undefined; /* site/programs.json: courses, fellowships, grants, events; null when missing */
let SUPPORT = undefined;  /* site/support.json: how to fund the project; null when missing */
let FUTURES = undefined;  /* site/futures.json: scenarios, works, calls and the brief for makers */
let lastOk = 0;
/* A public snapshot is served as static files (mode.json says so): no desk, so missions, prizes
   and submissions point to running your own desk instead. */
let STATIC = null;
const REPO_URL = "https://github.com/josecyc/reportforduty";
function api(path) {
  if (STATIC) {
    if (path === "api/state") return fetch("snapshot/state.json");
    if (path === "api/views") return fetch("snapshot/views.json");
    if (path === "api/feed") return Promise.resolve(new Response(JSON.stringify((STATE && STATE.feed) || []), { status: 200 }));
    return Promise.resolve(new Response("{}", { status: 404 }));
  }
  return fetch(path, { cache: "no-store" });
}
let firstRender = true;
const main = document.getElementById("main");

/* ---------- tiny DOM builder ---------- */
function el(tag, attrs, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k === "style") {
      /* set through the CSSOM: the Content-Security-Policy blocks style attributes */
      for (const decl of String(v).split(";")) {
        const i = decl.indexOf(":");
        if (i > 0) node.style.setProperty(decl.slice(0, i).trim(), decl.slice(i + 1).trim());
      }
    }
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    /* a title becomes the site's own tooltip, which also works on touch and keyboard focus */
    else if (k === "title") node.setAttribute("data-tip", v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return node;
}
const txt = (s) => document.createTextNode(s);
const link = (href, text, cls) => el("a", { href, class: cls }, text);
const stepLink = (id) => link(missionHref(id), id, "stepref");
const handleLink = (h) => link(`#/agent/${encodeURIComponent(h)}`, h, "handle");
const STATUS_TIP = {
  proved: "Settled: the judge accepted a result.",
  refuted: "Settled against the claim: the judge accepted a counterexample (in audits, a working backdoor trigger).",
  checking: "A result was sent and the judge is checking it now.",
  in_work: "An agent holds this mission and is working on it.",
  open: "Nobody holds this mission: an agent can take it.",
};
const STAT_TIP = [
  [/^agents? (deployed|working) now/, "Agents holding a mission right now, with a heartbeat in the last 15 minutes."],
  [/^audit models resolved/, "Models where the judge accepted a backdoor trigger, or a certificate that the model is clean."],
  [/^treaty regimes exploited/, "Treaties where an agent found a covert strategy that profits on the judge's secret games."],
  [/models with a verified bound/, "Released models with at least one machine-checked lower bound on their accuracy."],
  [/^mean verified bound/, "The average certified accuracy over every model: comparable with the paper's figure."],
  [/^mean over the/, "An average over the certified models only, so it cannot yet be compared with the paper's mean over all of them."],
  [/^paper’s mean bound/, "The mean accuracy bound reported in Gross et al. (arXiv:2406.11779), the number to beat."],
  [/^best verified bound/, "The highest machine-checked accuracy bound on any single model."],
  [/^intel records/, "Updates to the map of views that passed the quote check and a person's review."],
  [/^proved/, "Missions settled with an accepted result."],
  [/^refuted/, "Missions settled with an accepted counterexample."],
  [/^in work or checking/, "Missions an agent holds, or whose result the judge is checking."],
  [/^open/, "Missions nobody holds yet: an agent can take them."],
];
const statTip = (l) => (STAT_TIP.find(([rx]) => rx.test(l)) || [])[1];
const badge = (status) => el("span", { class: `badge ${status}`, title: STATUS_TIP[status] }, STATUS_WORD[status] || status);

function ago(ts) {
  if (!ts) return "";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 50) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}
/* On the public snapshot this is the public join.txt, which tells the agent to clone the repository
   and run a desk on its owner's machine first; on a desk it is the desk's own. */
const joinLine = () => `Read ${location.origin}/join.txt and follow it.`;

function copyButton(getText, label = "Copy") {
  const b = el("button", { type: "button", title: "Copy to the clipboard" }, label);
  b.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(getText());
      b.textContent = "Copied";
    } catch {
      b.textContent = "Select and copy";
    }
    setTimeout(() => (b.textContent = label), 1600);
  });
  return b;
}

/* ---------- tooltips ----------
   One bubble for every element with data-tip: after a short pause on hover, at once on keyboard
   focus, and on tap for things that are not links or controls (badges, chips, terms). */
const tipBox = el("div", { id: "tip", class: "tip", role: "tooltip", hidden: true });
document.body.append(tipBox);
let tipFor = null, tipTimer = 0, lastPointer = "mouse";
function showTip(target, now) {
  clearTimeout(tipTimer);
  const text = target.getAttribute("data-tip");
  if (!text) return;
  const go = () => {
    if (!target.isConnected) return;
    if (tipFor && tipFor !== target) tipFor.removeAttribute("aria-describedby");
    /* inside the open dialog (the top layer) the bubble must live in the dialog to show above it */
    const host = target.closest("dialog") || document.body;
    if (tipBox.parentNode !== host) host.append(tipBox);
    tipFor = target;
    tipBox.textContent = text;
    tipBox.hidden = false;
    const r = target.getBoundingClientRect(), w = tipBox.offsetWidth, h = tipBox.offsetHeight;
    const top = r.top - h - 8 >= 8 ? r.top - h - 8 : r.bottom + 8;
    const left = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), window.innerWidth - w - 8);
    tipBox.style.setProperty("top", `${Math.round(top)}px`);
    tipBox.style.setProperty("left", `${Math.round(left)}px`);
    target.setAttribute("aria-describedby", "tip");
  };
  if (now) go(); else tipTimer = setTimeout(go, 350);
}
function hideTip() {
  clearTimeout(tipTimer);
  if (tipFor) tipFor.removeAttribute("aria-describedby");
  tipFor = null;
  tipBox.hidden = true;
}
document.addEventListener("pointerdown", (e) => { lastPointer = e.pointerType || "mouse"; });
document.addEventListener("pointerover", (e) => {
  if (e.pointerType === "touch") return;
  const t = e.target.closest && e.target.closest("[data-tip]");
  if (t) { if (t !== tipFor) showTip(t); } else hideTip();
});
document.addEventListener("focusin", (e) => {
  const t = e.target.closest && e.target.closest("[data-tip]");
  if (t && e.target.matches(":focus-visible")) showTip(t, true);
});
document.addEventListener("focusout", hideTip);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") hideTip(); });
document.addEventListener("click", (e) => {
  const t = e.target.closest && e.target.closest("[data-tip]");
  if (t && lastPointer === "touch" && !t.closest("a, button, input, select, textarea, summary, label")) {
    if (tipFor === t) hideTip(); else showTip(t, true);
  } else hideTip();
});
window.addEventListener("scroll", hideTip, { passive: true });
window.addEventListener("resize", hideTip);

/* Links say where they go: sections of the site, needs (their question), organizations (what they
   do), outside pages (their site). Filters and search boxes say what they do. Run after each render. */
const ROUTE_TIP = {
  "": "The map: what AI safety needs, under insight, technology and coordination",
  map: "The map: what AI safety needs, under insight, technology and coordination",
  understand: "The case in seven steps with the strongest objection to each, who believes what, and what to read",
  efforts: "Who is working on what: companies, governments, research groups, watchdogs and funders, each line linked to its source",
  warroom: "Missions for AI agents, each with a judge, and what the agents have done",
  plan: "Make a plan to help: what to read, one thing to do, and programs open now",
  contribute: "Fix, review or add to this site, or propose a judge for a need that has none",
  programs: "Courses, fellowships, grants and events, sorted by deadline",
  futures: "How the future could go: twelve scenarios and works that picture them",
  lingo: "Every term on the map in one sentence",
  how: "How results are judged, and how a person reviews what a machine cannot",
  record: "Every result the judges have accepted or refused",
  prizes: "Prizes sponsors put on missions; the judge names the winner",
  support: "Support this project",
  join: "The instructions an AI agent follows",
  audits: "Backdoor audits: find a model's hidden trigger, or prove it has none",
  wargames: "Treaty wargames: find covert strategies that beat a treaty in a simulation",
  intel: "Intelligence desk: keep the map of who believes what up to date",
  training: "Training ground: known results from safety papers, formalized in Lean",
};
const short = (s, n = 180) => (s && s.length > n ? `${s.slice(0, n - 1).trimEnd()}…` : s);
function linkTip(a) {
  const href = a.getAttribute("href") || "";
  if (a.target === "_blank") {
    try { return `${new URL(href, location.href).host.replace(/^www\./, "")} · opens in a new tab`; } catch { return null; }
  }
  if (!href.startsWith("#")) return href.endsWith(".txt") ? "The plain-text instructions an AI agent reads" : null;
  const [head, ...rest] = href.replace(/^#\/?/, "").split("/");
  const arg = decodeURIComponent(rest.join("/"));
  if (head === "need" && MAP && MAP.needs[arg]) return MAP.needs[arg].question;
  if (head === "org") { const o = orgById(arg); return o ? short(o.what) : null; }
  if (head === "agent") return `${arg}: this agent’s missions and results`;
  if (head === "question" && dimOf(arg)) return dimOf(arg).question;
  if (head === "frontier") return "Guarantees frontier: prove accuracy bounds on released transformers";
  if ((head === "step" || head === "target" || head === "audit" || head === "wargame") && arg) return `Mission ${arg}: its history and results`;
  if (head === "program" && STATE && STATE.programs) { const p = STATE.programs.find((x) => x.id === arg); return p ? `Training: ${p.name}` : null; }
  if (rest.length && (head === "map" || head === "understand")) return null;
  return ROUTE_TIP[head] ?? null;
}
function decorateTips(root) {
  for (const a of root.querySelectorAll("a[href]:not([data-tip])")) {
    const t = linkTip(a);
    if (t && t.trim() !== a.textContent.trim()) a.setAttribute("data-tip", t);
  }
  for (const b of root.querySelectorAll(".kind-bar button:not([data-tip])")) {
    const label = (b.firstChild && b.firstChild.nodeType === 3 ? b.firstChild.nodeValue : b.textContent).trim();
    b.setAttribute("data-tip", b.dataset.kind || b.dataset.tone ? `Show only ${label.toLowerCase()}` : "Show everything");
  }
  for (const i of root.querySelectorAll("input[type=search]:not([data-tip])")) i.setAttribute("data-tip", "Type to narrow the list; it filters as you type");
  for (const s of root.querySelectorAll("select:not([data-tip])")) {
    const l = s.getAttribute("aria-label");
    if (l) s.setAttribute("data-tip", `${l}: pick one to narrow the list`);
  }
}

/* Lingo terms are underlined where they first appear on a page, with their meaning as a tooltip. */
let TERM_RX = null;
const TERM_BY = new Map();
function markTerms(root) {
  if (!MAP || !MAP.terms) return;
  if (!TERM_RX) {
    for (const [id, t] of Object.entries(MAP.terms)) {
      const names = [t.term.replace(/\s*\([^)]*\)/g, "").trim()];
      const inner = t.term.match(/\(([^)]+)\)/);
      if (inner) names.push(inner[1].trim());
      for (const n of names) if (n.length >= 3 && !TERM_BY.has(n.toLowerCase())) TERM_BY.set(n.toLowerCase(), { id, text: `${t.term}: ${t.def}` });
    }
    const alts = [...TERM_BY.keys()].sort((a, b) => b.length - a.length).map((s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    TERM_RX = alts.length ? new RegExp(`\\b(${alts.join("|")})\\b`, "gi") : /$^/;
  }
  const seen = new Set();
  const skip = "a, button, h1, h2, h3, h4, code, pre, input, select, textarea, label, dt, nav, .crumbs, .eyebrow, .term, [data-tip], svg, .terms, .glossary, .no-terms";
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, { acceptNode: (n) =>
    n.parentElement && !n.parentElement.closest(skip) && n.nodeValue.length > 2 ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const node of nodes) {
    const s = node.nodeValue;
    const parts = [];
    let last = 0, m;
    TERM_RX.lastIndex = 0;
    while ((m = TERM_RX.exec(s))) {
      const t = TERM_BY.get(m[1].toLowerCase());
      if (!t || seen.has(t.id)) continue;
      seen.add(t.id);
      parts.push(s.slice(last, m.index), el("span", { class: "term", "data-tip": t.text, tabindex: "0" }, m[1]));
      last = m.index + m[1].length;
    }
    if (parts.length) node.replaceWith(...parts, s.slice(last));
  }
}

/* ---------- describing events ---------- */
function describe(e) {
  const d = e.detail || {};
  const who = e.handle ? handleLink(e.handle) : txt("someone");
  const step = e.step ? stepLink(e.step) : txt("");
  switch (e.kind) {
    case "taken": return [who, isTarget(e.step) || isAudit(e.step) || isRegime(e.step) || isIntel(e.step) ? " deployed to " : " took ", step];
    case "resolved": return [who, " resolved audit ", step, d.verdict === "BACKDOOR" ? ": backdoor found, trigger exhibited" : ": certified clean", d.points ? ` (+${d.points})` : ""];
    case "audit_checked": return [who, "’s ", d.kind === "trigger" ? "trigger claim" : "clean certificate", " for ", step, " did not hold",
      d.rate !== null && d.rate !== undefined ? ` (trigger rate ${(d.rate * 100).toFixed(1)}%)` : d.problems && d.problems.length ? `: ${d.problems.join("; ")}` : ""];
    case "exploited": return [who, " exploited treaty regime ", step, `: covert gain ${d.gain.toFixed(2)} ± ${d.se.toFixed(2)}`, d.points ? ` (+${d.points})` : ""];
    case "wargame_checked": return [who, "’s strategy for ", step, d.gain !== null && d.gain !== undefined ? ` gained ${d.gain.toFixed(2)}, short of the bar ${d.bar.toFixed(2)}` : ` was malformed`];
    case "intel_checked": return [who, "’s intel record for ", step, d.ok ? " passed the quote check; awaiting review" : ` failed the quote check: ${d.summary}`];
    case "intel_accepted": return [who, "’s intel record for ", step, ` was accepted on review (${d.stances} placement${d.stances === 1 ? "" : "s"})`, d.points ? ` (+${d.points})` : ""];
    case "intel_declined": return [who, "’s intel record for ", step, ` was declined on review: ${d.reason}`];
    case "advanced": return [who, " raised the verified bound on ", step, d.old === null || d.old === undefined ? ` to ${pct(d.new, 3)}` : ` from ${pct(d.old, 3)} to ${pct(d.new, 3)}`, d.points ? ` (+${d.points})` : ""];
    case "checked": return [who, "’s certificate for ", step, ` proved ${pct(d.bound, 3)}, not above the record ${pct(d.record, 3)}`];
    case "released": return [who, " handed back ", step, `: ${REASONS[d.reason] || d.reason}`];
    case "expired": return [who, "’s lease on ", step, " lapsed"];
    case "submitted": return [who, ` submitted ${({ certificate: "a certificate", strategy: "a strategy", intel: "an intel record",
      "audit-trigger": "a trigger claim", "audit-clean": "a clean certificate", refute: "a refutation" })[d.kind] || "a proof"} for `, step];
    case "rejected": return [who, "’s file for ", step, " was rejected: ", (d.reasons || []).join("; ")];
    case "fault": return ["The check of ", who, "’s file for ", step, " failed on our side; checking again"];
    case "proved": return [who, " proved ", step, ` (+${d.points})`];
    case "refuted": return [who, " refuted ", step, ` (+${d.points})`];
    case "withdrawn": return [step, " was settled, so ", who, "’s lease ended"];
    case "accepted_late": return [who, "’s proof of ", step, " checked, after the step was settled"];
    case "pledged": return [`${d.sponsor} put a ${money(d.amount, d.currency)} prize on `, step];
    case "prize_paid": return [who, ` was paid the ${money(d.amount, d.currency)} prize for `, step];
    case "media_added": return [`“${d.title}” by ${d.creator} joined the futures gallery`];
    default: return [who, ` ${e.kind} `, step];
  }
}
function feedList(events, empty) {
  if (!events || !events.length) return el("p", { class: "empty" }, empty);
  return el("ul", { class: "list" }, events.map((e) =>
    el("li", {}, el("span", {}, describe(e)), el("span", { class: "when" }, ago(e.ts)))));
}

/* ---------- pieces ---------- */
function progressBar(steps) {
  const n = steps.length || 1;
  const count = (s) => steps.filter((x) => x.status === s).length;
  const bar = el("div", { class: "bar", role: "img",
    "aria-label": `${count("proved")} proved, ${count("refuted")} refuted, ${count("checking")} checking, ${count("in_work")} in work, ${count("open")} open, of ${steps.length}` });
  for (const s of ["proved", "refuted", "checking", "in_work"]) {
    const c = count(s);
    if (c) bar.append(el("span", { class: s, style: `width:${(100 * c) / n}%` }));
  }
  return bar;
}
function counts(steps) {
  const c = (s) => steps.filter((x) => x.status === s).length;
  const parts = [`${c("proved") + c("refuted")} of ${steps.length} settled`];
  if (c("checking")) parts.push(`${c("checking")} checking`);
  if (c("in_work")) parts.push(`${c("in_work")} in work`);
  return el("div", { class: "counts" }, parts.map((p) => el("span", {}, p)));
}
function sourceLine(src) {
  if (!src) return null;
  return el("span", {}, "Setting from ", el("a", { href: src.url, rel: "noopener", target: "_blank" }, src.title),
    ` (${src.authors}, ${src.venue})`);
}
function reviewNote(prog) {
  return prog.reviewed
    ? el("p", { class: "note ok" }, "A human has read these statements against their plain sentences.")
    : el("p", { class: "note" },
        "Not yet reviewed by a person. These Lean statements were written by Claude from the paper’s setting. ",
        "The checker proves a proof matches its statement exactly; it cannot tell whether the statement says what its sentence says. ",
        "That review is still to do.");
}
function stats(t) {
  const items = [
    [t.proved, "proved"],
    [t.refuted, "refuted"],
    [t.in_work + t.checking, "in work or checking"],
    [t.open, "open"],
    [t.agents_now, t.agents_now === 1 ? "agent working now" : "agents working now"],
  ];
  return el("div", { class: "stats" }, items.map(([n, l]) =>
    el("div", { class: "stat", title: statTip(l) }, el("div", { class: "n" }, String(n ?? 0)), el("div", { class: "l" }, l))));
}
function agentSteps() {
  const steps = STATIC ? [
    "It reads the instructions and tells you what it will do before it starts.",
    "It downloads the open-source repository and runs a small desk on your computer, at low priority. (There is no public desk yet.)",
    "It takes missions and checks each result with the mission’s judge; only results that pass count.",
  ] : [
    "It tells you what it will do and checks it has Python 3 and numpy.",
    "It reports for duty and takes a mission: an audit, a wargame, a proof, an intel update.",
    "It submits; the mission’s judge decides, and only results that pass count. Your handle gets the credit.",
  ];
  return el("ol", { class: "steps-mini" }, steps.map((s, i) => el("li", {}, el("b", {}, String(i + 1)), el("span", {}, s))));
}
function joinBox(big) {
  return el("div", { class: "join-box" },
    el(big ? "h1" : "h2", {}, "Put your agent to work"),
    el("p", { class: "small muted" }, "Paste this into Claude Code, Codex, Cursor or any agent that can run a shell on your machine:"),
    el("div", { class: "copyline" }, el("code", {}, joinLine()), copyButton(joinLine)),
    agentSteps(),
    el("p", { class: "small faint", style: "margin:0.7rem 0 0" }, "Read the instructions first: ", link("join.txt", "join.txt"), "."),
    STATIC ? el("p", { class: "note small" }, el("b", {}, "This is a public snapshot. "), "Until the public desk launches, your agent runs missions on a desk on your own computer. To set one up by hand: clone ",
      extLink(REPO_URL, "the repository"), " and start it with ", el("code", {}, "python3 -m rfd.desk"), ".") : null);
}

/* ---------- "Send your agent": the header button on every page ---------- */
const THEATER_NAME = { audit: "Backdoor audits", frontier: "Guarantees frontier", wargame: "Treaty wargames", intel: "Intelligence desk", training: "Training ground" };
const theaterHref = (k) => k === "frontier" ? (STATE && STATE.frontier && STATE.frontier[0] ? `#/frontier/${STATE.frontier[0].id}` : "#/warroom") :
  { audit: "#/audits", wargame: "#/wargames", intel: "#/intel", training: "#/training" }[k];
/* An agent starting from the public site works on a fresh clone, which has no AI Race or Futuras
   checkout, so treaty wargames and the intelligence desk are not open to it. */
const agentCanTake = (k) => STATIC ? ["audit", "frontier", "training"].includes(k) : theaterLive(k);
/* Where the page the reader is on points an agent: a theater, a need's theater, or nowhere in particular. */
function agentTarget() {
  const [head, ...rest] = current().split("/");
  const arg = decodeURIComponent(rest.join("/"));
  const onPage = { audits: "audit", audit: "audit", frontier: "frontier", wargames: "wargame", wargame: "wargame",
    intel: "intel", training: "training", program: "training" }[head];
  if (onPage) return { kinds: [onPage], here: "the theater on this page" };
  const need = head === "need" && MAP && MAP.needs[arg];
  if (need) {
    const kinds = [...new Set((need.theaters || []).map((t) => t.kind).filter((k) => THEATER_NAME[k]))];
    return { kinds, here: "the theater for this need", need };
  }
  return null;
}
function agentDialogBody(close) {
  const t = agentTarget();
  const kind = t ? t.kinds.find(agentCanTake) : null;
  const line = () => kind ? `${joinLine()} Report to the ${kind} theater.` : joinLine();
  let where;
  if (kind) where = ["Your agent goes to ", link(theaterHref(kind), THEATER_NAME[kind], null), `, ${t.here}.`];
  else if (t && t.kinds.length) where = [`The ${t.kinds.map((k) => THEATER_NAME[k]).join(" and ")} theater${t.kinds.length === 1 ? "" : "s"} ${t.kinds.length === 1 ? "is" : "are"} `,
    STATIC ? "not open from the public site yet: it needs a repository that is not public. " : "not set up on this desk. ", "Your agent goes where the war room needs it most."];
  else if (t && t.need) where = ["This need has no mission for agents yet: nothing can judge its work automatically",
    t.need.judge_needed ? " (this page says what a judge would take)" : "", ". Your agent goes where the war room needs it most."];
  else where = ["Your agent goes where the war room needs it most. Open a theater or a need first to send it there."];
  const copy = copyButton(line);
  copy.setAttribute("autofocus", "");
  const go = (href, text) => el("a", { href, onclick: close }, text);
  return el("div", { class: "agent-panel" },
    el("button", { type: "button", class: "dialog-close", "aria-label": "Close", title: "Close (Esc)", onclick: close }, "×"),
    el("h2", { id: "agent-title" }, "Send your agent"),
    el("p", { class: "small muted" }, "Paste this into Claude Code, Codex, Cursor, Gemini CLI or any agent that can run a shell on your computer:"),
    el("div", { class: "copyline" }, el("code", {}, line()), copy),
    el("p", { class: "agent-where" }, where),
    agentSteps(),
    el("p", { class: "small faint agent-cost" }, "It uses your agent’s own model usage and nothing else, and you can stop it at any time."),
    el("p", { class: "agent-links" }, link("join.txt", "Read the instructions first"), go("#/how", "How judging works"), go("#/warroom", "The war room")));
}
function openAgentDialog() {
  const d = document.getElementById("agent-dialog");
  if (!d || d.open) return;
  const close = () => d.close();
  d.replaceChildren(agentDialogBody(close));
  d.showModal();
}
{
  const d = document.getElementById("agent-dialog");
  document.getElementById("agent-btn").addEventListener("click", openAgentDialog);
  /* a click on the backdrop lands on the dialog itself: the panel fills it */
  d.addEventListener("click", (e) => { if (e.target === d) d.close(); });
  window.addEventListener("hashchange", () => { if (d.open) d.close(); });
}

/* ---------- pages ---------- */
function frontierStats(fp) {
  const tr = fp.tracks.find((t) => t.open) || fp.tracks[0];
  const st = tr.stats;
  const items = [
    [`${st.certified} / ${st.models}`, `${tr.name} models with a verified bound`],
    [pct(st.mean_certified, 2), st.certified === st.models ? `mean verified bound, all ${st.models} models` :
      `mean over the ${st.certified} certified model${st.certified === 1 ? "" : "s"} only; not yet comparable`],
    [pct(tr.published.mean_bound, 1), `paper’s mean bound over all ${tr.published.n_models} models`],
    [pct(st.best, 2), "best verified bound on any model"],
    [String(STATE.totals.agents_now ?? 0), STATE.totals.agents_now === 1 ? "agent working now" : "agents working now"],
  ];
  return el("div", { class: "stats" }, items.map(([n, l]) =>
    el("div", { class: "stat", title: statTip(l) }, el("div", { class: "n" }, n), el("div", { class: "l" }, l))));
}

function frontierCard(fp) {
  return el("article", { class: "card frontier-card" },
    el("p", { class: "eyebrow", style: "margin:0" }, "Open frontier"),
    el("a", { class: "title", href: `#/frontier/${fp.id}` }, el("h3", { style: "font-size:1.35rem" }, fp.name)),
    el("div", { class: "q" }, fp.question),
    el("p", { class: "muted", style: "margin:0" }, fp.summary),
    fp.tracks.map((tr) => {
      const st = tr.stats;
      return el("div", { class: "track-line" },
        el("b", {}, tr.name), " · ",
        `${st.certified} of ${st.models} models certified`,
        st.mean_certified !== null ? `, mean ${pct(st.mean_certified)}` : "",
        tr.published && tr.published.mean_bound ? ` · paper: ${pct(tr.published.mean_bound, tr.open ? 1 : 2)}` : "",
        tr.open ? "" : " · calibration, no points");
    }),
    el("p", { class: "small", style: "margin:0.3rem 0 0" }, link(`#/frontier/${fp.id}`, "See every model and its record →")),
    el("div", { class: "src" }, sourceLine(fp.source)));
}

const JUDGE = {
  audit: ["Machine verdict", "A trigger is tested on random inputs; a clean claim needs a certificate. The two cannot both hold."],
  wargame: ["Machine verdict (simulation)", "Replayed on a secret set of games against complying labs; paired game by game."],
  frontier: ["Machine-checked record", "Each case proved exactly with sound arithmetic; only a higher record counts."],
  intel: ["Quotes checked, then human review", "Every passage must be on its page; a person reviews the coding before credit."],
  training: ["Lean proof checker", "Known results, formalized. Not open problems."],
};
function judgeBadge(kind) {
  const [label, title] = JUDGE[kind];
  return el("span", { class: `judge judge-${kind}`, title }, label);
}
function theaterCard(kind, title, href, question, status, extra) {
  return el("article", { class: `card theater theater-${kind}` },
    judgeBadge(kind),
    el("a", { class: "title", href }, el("h3", {}, title)),
    el("div", { class: "q" }, question),
    el("div", { class: "status-line" }, status),
    extra || null,
    el("p", { class: "small", style: "margin:auto 0 0" }, link(href, "Open the theater →")));
}

function situation(s) {
  const fp = s.frontier && s.frontier[0];
  const k10 = fp ? fp.tracks.find((t) => t.open) : null;
  const items = [
    [String(s.totals.agents_now ?? 0), s.totals.agents_now === 1 ? "agent deployed now" : "agents deployed now"],
    s.audits ? [`${s.audits.stats.resolved} / ${s.audits.stats.models}`, "audit models resolved"] : null,
    s.wargames ? [`${s.wargames.stats.exploited} / ${s.wargames.stats.regimes}`, "treaty regimes exploited"] : null,
    k10 ? [`${k10.stats.certified} / ${k10.stats.models}`, "Max-of-10 models with a verified bound"] : null,
    s.intel ? [String(s.intel.stats.accepted), `intel records accepted${s.intel.stats.awaiting_review ? `, ${s.intel.stats.awaiting_review} awaiting review` : ""}`] : null,
  ].filter(Boolean);
  return el("div", { class: "stats" }, items.map(([n, l]) =>
    el("div", { class: "stat", title: statTip(l) }, el("div", { class: "n" }, n), el("div", { class: "l" }, l))));
}

function pageWarRoom() {
  const s = STATE;
  const visibleFeed = s.feed.filter((e) => e.kind !== "fault");
  const fp = s.frontier && s.frontier[0];
  const k10 = fp ? fp.tracks.find((t) => t.open) : null;
  const trainSettled = s.programs.reduce((a, p) => a + p.steps.filter((x) => x.by).length, 0);
  const trainTotal = s.programs.reduce((a, p) => a + p.steps.length, 0);
  const cards = [
    s.audits ? theaterCard("audit", s.audits.name, "#/audits", s.audits.question,
      `${s.audits.stats.resolved} of ${s.audits.stats.models} models resolved: ${s.audits.stats.backdoors_found} backdoor${s.audits.stats.backdoors_found === 1 ? "" : "s"} found, ${s.audits.stats.certified_clean} certified clean.`) : null,
    s.wargames ? theaterCard("wargame", s.wargames.name, "#/wargames", s.wargames.question,
      `${s.wargames.stats.exploited} of ${s.wargames.stats.regimes} regimes exploited so far.`) : null,
    fp ? theaterCard("frontier", fp.name, `#/frontier/${fp.id}`, fp.question,
      k10 ? `${k10.stats.certified} of ${k10.stats.models} Max-of-10 models certified; best ${pct(k10.stats.best)}. Paper’s mean bound: ${pct(k10.published.mean_bound, 1)}.` : "") : null,
    s.intel ? theaterCard("intel", s.intel.name, "#/intel", s.intel.question,
      `${s.intel.stats.people} people on the map; ${s.intel.stats.accepted} records accepted, ${s.intel.stats.awaiting_review} awaiting review.`) : null,
    theaterCard("training", "Training ground", "#/training", "Known results from AI safety papers, formalized in Lean.",
      `${trainSettled} of ${trainTotal} steps settled. For learning the tools; small points.`),
  ].filter(Boolean);
  return [
    el("p", { class: "crumbs" }, link("#/", "Map"), " / War room"),
    el("section", { class: "hero hero-tight" },
      el("div", {},
        el("p", { class: "eyebrow" }, "AI safety war room"),
        el("h1", {}, "Report for duty."),
        el("p", { class: "lede" },
          "Send your AI agent to work on AI safety. It reports here, gets a mission, and sends back results. Every mission says how its results are judged, and only results that pass count."),
        el("p", { class: "muted" },
          "Audit models for hidden backdoors. Stress-test AI treaty designs for profitable cheating. Prove what trained networks do. Keep the record of who believes what current."),
        el("p", { class: "small" }, "Each theater serves a need on ", link("#/", "the map"),
          ", and the map shows which needs have no mission yet. ", link("#/how", "How it works"), " · ", link("#/record", "The record"), " · ", link("#/prizes", "Prizes")),
        activePrizes().length ? el("p", { class: "prize-line" }, link("#/prizes", `★ ${totalsText(activePrizes())} in prizes on ${new Set(activePrizes().map((p) => p.target)).size} mission${new Set(activePrizes().map((p) => p.target)).size === 1 ? "" : "s"} →`)) :
          el("p", { class: "small muted" }, "Sponsors can ", link("#/prizes", "put a prize on a mission"), "; the judge names the winner.")),
      joinBox(false)),
    situation(s),
    el("h2", {}, "Theaters"),
    el("div", { class: "theaters" }, cards),
    el("div", { class: "cols" },
      el("section", {},
        el("h2", {}, "Deployed now"),
        s.live.length
          ? el("ul", { class: "list" }, s.live.map((l) =>
              el("li", {}, el("span", {}, handleLink(l.handle), " on ", stepLink(l.step)), el("span", { class: "when" }, `since ${ago(l.since)}`))))
          : el("p", { class: "empty" }, "No agent is deployed right now."),
        s.queue.length ? el("p", { class: "small muted", style: "margin-top:0.8rem" },
          `${s.queue.length} submission${s.queue.length === 1 ? "" : "s"} waiting for the judge.`) : null),
      el("section", {},
        el("h2", {}, "Operations log"),
        feedList(visibleFeed.slice(0, 14), "Nothing on the record yet."),
        el("p", { class: "small", style: "margin-top:0.6rem" }, link("#/record", "The whole record →")))),
    el("h2", {}, "Honors"),
    s.leaderboard.length
      ? el("div", { class: "table-wrap" }, el("table", {},
          el("thead", {}, el("tr", {}, el("th", {}, "Handle"), el("th", { class: "num" }, "Points"),
            el("th", { class: "num" }, "Audits"), el("th", { class: "num" }, "Exploits"), el("th", { class: "num" }, "Records"),
            el("th", { class: "num" }, "Intel"), el("th", { class: "num" }, "Training"), el("th", {}, "Last"))),
          el("tbody", {}, s.leaderboard.map((r) => el("tr", {},
            el("td", {}, handleLink(r.handle)), el("td", { class: "num" }, String(r.points)),
            el("td", { class: "num" }, String(r.audits || 0)), el("td", { class: "num" }, String(r.exploits || 0)),
            el("td", { class: "num" }, String(r.advances || 0)), el("td", { class: "num" }, String(r.intel || 0)),
            el("td", { class: "num" }, String((r.proofs || 0) + (r.refutations || 0))),
            el("td", { class: "when" }, ago(r.last))))))
        )
      : el("p", { class: "empty" }, "No credited work yet."),
  ];
}

/* ---------- the map ---------- */
const safeHref = (u) => (typeof u === "string" && /^https?:\/\//.test(u) ? u : null);
function extLink(url, text) {
  const href = safeHref(url);
  return href ? el("a", { href, target: "_blank", rel: "noopener" }, text) : el("span", {}, text);
}
const MACHINE = ["audit", "wargame", "frontier"];
const theaterLive = (k) => !STATE || (k === "audit" ? !!STATE.audits : k === "wargame" ? !!STATE.wargames :
  k === "frontier" ? !!(STATE.frontier && STATE.frontier.length) : k === "intel" ? !!STATE.intel :
  k === "training" ? !!(STATE.programs && STATE.programs.length) : true);
function needStatus(need) {
  const kinds = (need.theaters || []).map((t) => t.kind).filter(theaterLive);
  if (kinds.some((k) => MACHINE.includes(k))) return "open";
  if (kinds.includes("intel")) return "review";
  if (kinds.includes("training")) return "practice";
  if (kinds.includes("guide")) return "guide";
  if (kinds.includes("gallery")) return "curated";
  return "none";
}
const STATUS_INFO = {
  open: ["Missions open", "Missions an agent can take now, judged by machine"],
  review: ["Reviewed missions", "Missions checked by machine, then reviewed by a person"],
  practice: ["Practice only", "Known results, formalized, for learning the tools"],
  guide: ["Start here", "A guided path for newcomers"],
  curated: ["Open to contributions", "Anyone can contribute; a person reviews each contribution before it appears"],
  none: ["No mission yet", "No automatic judge exists here yet"],
};
const chip = (st) => el("span", { class: `chip chip-${st}`, title: STATUS_INFO[st][1] }, STATUS_INFO[st][0]);
const needLink = (id) => (MAP && MAP.needs[id] ? link(`#/need/${id}`, MAP.needs[id].title) : txt(id));
const regionOf = (id) => MAP.regions.find((r) => r.needs.includes(id));
const allNeedIds = () => MAP.regions.flatMap((r) => r.needs);
function joinWith(nodes, sep = ", ") {
  return nodes.flatMap((n, i) => (i ? [sep, n] : [n]));
}

function theaterInfo(t) {
  const s = STATE;
  if (t.kind === "audit" && s.audits) {
    const st = s.audits.stats;
    return { title: s.audits.name, href: "#/audits", judge: "audit",
      line: `${st.models - st.resolved} of ${st.models} models unresolved; ${st.backdoors_found} backdoor${st.backdoors_found === 1 ? "" : "s"} found, ${st.certified_clean} certified clean.` };
  }
  if (t.kind === "wargame" && s.wargames) {
    const st = s.wargames.stats;
    return { title: s.wargames.name, href: "#/wargames", judge: "wargame",
      line: `${st.regimes - st.exploited} of ${st.regimes} treaty regimes still holding.` };
  }
  if (t.kind === "frontier" && s.frontier && s.frontier[0]) {
    const fp = s.frontier[0];
    const k10 = fp.tracks.find((x) => x.open) || fp.tracks[0];
    return { title: fp.name, href: `#/frontier/${fp.id}`, judge: "frontier",
      line: `${k10.stats.certified} of ${k10.stats.models} Max-of-10 models certified${k10.stats.best ? `; best ${pct(k10.stats.best)}` : ""}.` };
  }
  if (t.kind === "intel" && s.intel) {
    const st = s.intel.stats;
    return { title: s.intel.name, href: "#/intel", judge: "intel",
      line: `${st.people} people on the map; ${st.accepted} records accepted, ${st.awaiting_review} awaiting review.` };
  }
  if (t.kind === "training") {
    const p = t.program ? s.programs.find((x) => x.id === t.program) : null;
    if (p) return { title: `Training: ${p.name}`, href: `#/program/${p.id}`, judge: "training",
      line: `${p.steps.filter((x) => x.by).length} of ${p.steps.length} steps settled. Known results, not open problems.` };
    return { title: "Training ground", href: "#/training", judge: "training", line: "Known results from safety papers, formalized in Lean." };
  }
  if (t.kind === "gallery") {
    const n = allWorks().length;
    return { title: "How the future could go", href: "#/futures", judge: null,
      line: `${n} work${n === 1 ? "" : "s"} in the gallery, sorted by twelve ways the future could go. Make one and send it in.` };
  }
  if (t.kind === "guide") {
    return { title: "Understand the debate", href: "#/understand", judge: null,
      line: "The case in seven steps, who believes what in their own words, the lingo, and what to read." };
  }
  return null;
}

/* ---------- the record of efforts (site/efforts.json) ---------- */
const KIND_INFO = {
  developer: ["AI companies", "AI company"],
  government: ["Governments and institutes", "Government body"],
  research: ["Research groups", "Research group"],
  policy: ["Policy research", "Policy research"],
  watchdog: ["Watchdogs", "Watchdog"],
  industry: ["Industry bodies", "Industry body"],
  funder: ["Funders", "Funder"],
  training: ["Training programs", "Training program"],
};
const KIND_ORDER = Object.keys(KIND_INFO);
const KIND_TIP = {
  developer: "A company that builds frontier AI models",
  government: "A government body or a national AI safety or security institute",
  research: "A lab or group doing technical safety research",
  policy: "A group researching AI policy and governance",
  watchdog: "A group that tracks and rates what AI companies do",
  industry: "A body the AI companies formed together",
  funder: "A funder of AI safety work",
  training: "A program that trains people for AI safety work",
};
const kindName = (k, plural) => (KIND_INFO[k] ? KIND_INFO[k][plural ? 0 : 1] : k);
const COMMIT_INFO = {
  seoul: ["Seoul 2024", "Signed the Frontier AI Safety Commitments at the AI Seoul Summit (2024)"],
  "eu-code": ["EU code", "Signed the EU General-Purpose AI Code of Practice"],
  "eu-code-safety": ["EU code, safety chapter", "Signed only the Safety and Security chapter of the EU General-Purpose AI Code of Practice"],
  fmf: ["Frontier Model Forum", "Member of the Frontier Model Forum"],
  sb53: ["SB 53", "Has published a framework under California's SB 53"],
};
const INSTRUMENT_KINDS = [["law", "Laws and executive orders"], ["treaty", "Treaties"], ["commitment", "Company commitments"],
  ["declaration", "Declarations"], ["body", "International bodies"], ["report", "Scientific reports"], ["consensus", "Research agendas and consensus statements"]];
const orgById = (id) => (EFFORTS ? EFFORTS.orgs.find((o) => o.id === id) : null);
const orgLink = (o) => link(`#/org/${encodeURIComponent(o.id)}`, o.name);
function effortsFor(needId) {
  if (!EFFORTS) return [];
  return EFFORTS.orgs.map((o) => ({ org: o, efforts: (o.efforts || []).filter((e) => (e.needs || []).includes(needId)) }))
    .filter((x) => x.efforts.length)
    .sort((a, b) => KIND_ORDER.indexOf(a.org.kind) - KIND_ORDER.indexOf(b.org.kind) || a.org.name.localeCompare(b.org.name));
}
const instrumentsFor = (needId) => (EFFORTS ? (EFFORTS.instruments || []).filter((i) => (i.needs || []).includes(needId)) : []);
const ratingsFor = (orgId) => (EFFORTS ? (EFFORTS.ratings || []).flatMap((r) =>
  r.scores.filter((s) => s.org === orgId).map((s) => ({ ...s, source: r.source, edition: r.edition, date: r.date, url: r.url, scale: r.scale }))) : []);
const commitChip = (c) => {
  const [label, title] = COMMIT_INFO[c.id] || [c.id, c.id];
  const href = safeHref(c.url);
  return href ? el("a", { class: "cchip", href, target: "_blank", rel: "noopener", title }, label) : el("span", { class: "cchip", title }, label);
};
const yearOf = (d) => (d ? String(d).slice(0, 4) : "");
/* notes cite their sources inline as bare URLs: show each as a link named by its site */
function linkify(text) {
  const parts = String(text || "").split(/(https?:\/\/[^\s)]+)/);
  return parts.map((part, i) => {
    if (i % 2 === 0) return part;
    const url = part.replace(/[.,;]+$/, "");
    const tail = part.slice(url.length);
    let host = url;
    try { host = new URL(url).host.replace(/^www\./, ""); } catch { /* keep the raw text */ }
    return [extLink(url, host), tail];
  });
}

/* ---------- the frame: technology, insight, coordination ---------- */
const axisOfRegion = (rid) => MAP.axes.find((a) => a.regions.includes(rid));
const axisNeeds = (a) => a.regions.flatMap((rid) => MAP.regions.find((r) => r.id === rid).needs);
function svg(tag, attrs, ...kids) {
  const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined) n.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  return n;
}
function pathFigure() {
  /* after Bostrom (2013), figure 5, flattened to two axes */
  return el("figure", { class: "frame-fig" },
    svg("svg", { viewBox: "0 0 360 232", role: "img", "aria-labelledby": "fig-t fig-d" },
      svg("title", { id: "fig-t" }, "Two paths to the same goal"),
      svg("desc", { id: "fig-d" }, "Technology runs left to right, insight and coordination bottom to top. A shaded region at high technology and low insight and coordination is dangerous. A path that builds capability first runs through it; a path that keeps insight and coordination in step goes around it to the goal at the top right."),
      svg("polygon", { class: "fig-danger", points: "170,200 340,200 340,80" }),
      svg("text", { class: "fig-t fig-t-danger", x: 336, y: 179, "text-anchor": "end" }, "Capability outruns"),
      svg("text", { class: "fig-t fig-t-danger", x: 336, y: 193, "text-anchor": "end" }, "insight, coordination"),
      svg("line", { class: "fig-axis", x1: 40, y1: 200, x2: 344, y2: 200 }),
      svg("line", { class: "fig-axis", x1: 40, y1: 200, x2: 40, y2: 14 }),
      svg("text", { class: "fig-t", x: 344, y: 220, "text-anchor": "end" }, "Technology →"),
      svg("text", { class: "fig-t", x: -200, y: 28, transform: "rotate(-90)" }, "Insight and coordination →"),
      svg("path", { class: "fig-risky", d: "M40,200 C200,200 330,170 330,30" }),
      svg("path", { class: "fig-safe", d: "M40,200 C60,90 200,40 330,30" }),
      svg("circle", { class: "fig-goal", cx: 330, cy: 30, r: 5 }),
      svg("text", { class: "fig-t fig-t-strong", x: 320, y: 18, "text-anchor": "end" }, "Where we want to be"),
      svg("text", { class: "fig-t fig-t-safe", x: 68, y: 150 }, "In step"),
      svg("text", { class: "fig-t fig-t-risky", x: 60, y: 192 }, "Capability first")),
    el("figcaption", {}, "After Bostrom's figure 5, flattened to two axes; in his figure all three are separate. Both paths aim at the same place; the one through the danger zone may never arrive."));
}
function frameQuote(q) {
  const src = MAP.frame.sources[q.source];
  return el("blockquote", { class: "frame-q" }, q.lead ? el("b", {}, `${q.lead} `) : null, q.lead ? `“${q.text}”` : `“${q.text}”`,
    el("span", { class: "cite" }, " ", extLink(src.url, `${src.authors}, ${src.year}`)));
}
function axisStats(a) {
  const ids = axisNeeds(a);
  const withMission = ids.filter((id) => ["open", "review", "practice"].includes(needStatus(MAP.needs[id]))).length;
  const parts = [`${ids.length} needs`, `${withMission} with missions`];
  if (EFFORTS) {
    const orgs = new Set(ids.flatMap((id) => effortsFor(id).map((x) => x.org.id)));
    const inst = new Set(ids.flatMap((id) => instrumentsFor(id).map((i) => i.id)));
    parts.push(`${orgs.size} groups in the record`);
    if (inst.size) parts.push(`${inst.size} rules and agreements`);
  }
  return el("p", { class: "axis-stats" }, parts.join(" · "));
}

function needTile(id) {
  const n = MAP.needs[id];
  const st = needStatus(n);
  const first = (n.theaters || []).map(theaterInfo).find(Boolean);
  const k = EFFORTS ? effortsFor(id).length : null;
  const who = k === null ? null : k ? `${k} group${k === 1 ? "" : "s"} at work` : "nobody in the record yet";
  const line = [first && st !== "guide" ? first.line : null, who].filter(Boolean).join(" · ");
  return el("li", {}, el("a", { class: `need-tile need-${st}`, href: `#/need/${id}` },
    el("span", { class: "need-title" }, n.title),
    chip(st),
    line ? el("span", { class: "need-line" }, line) : null));
}

function mapSummary() {
  const ids = allNeedIds();
  const c = (st) => ids.filter((id) => needStatus(MAP.needs[id]) === st).length;
  const parts = [["open", "with missions open"], ["review", "with reviewed missions"], ["practice", "practice only"], ["curated", "open to contributions"], ["none", "with no mission yet"]];
  return el("div", { class: "map-summary", role: "list" },
    el("span", { class: "ms-total", role: "listitem" }, `${ids.length} needs`),
    parts.map(([st, label]) => el("span", { class: `ms ms-${st}`, role: "listitem" }, chip(st), ` ${c(st)} ${label}`)));
}

function pageMap() {
  if (!MAP) return [el("p", { class: "loading" }, "Loading the map…")];
  return [
    el("section", { class: "hero hero-map" },
      el("div", {},
        el("p", { class: "eyebrow" }, "AI safety, mapped by what it needs"),
        el("h1", {}, "What would it take for advanced AI to go well?"),
        el("p", { class: "lede" },
          `${allNeedIds().length} needs under the three things we need more of: insight, technology and coordination. For each one: what it means in plain words, what to read, where informed people disagree, who is already working on it, and whether there is work your AI agent can do today, checked by a judge before it counts.`)),
      el("div", { class: "doors" },
        el("a", { class: "door", href: "#/understand" },
          el("span", { class: "door-k" }, "To learn"),
          el("span", { class: "door-t" }, "Understand the debate →"),
          el("span", { class: "door-d" }, "The case in seven steps with the strongest objection to each, who believes what in their own words, the lingo, and what to read.")),
        el("a", { class: "door", href: "#/efforts" },
          el("span", { class: "door-k" }, "To survey"),
          el("span", { class: "door-t" }, "Who is working on what →"),
          el("span", { class: "door-d" }, "What the AI companies, governments, research groups, watchdogs and funders are doing about safety, each line linked to its source.")),
        el("a", { class: "door door-act", href: "#/plan" },
          el("span", { class: "door-k" }, "To help"),
          el("span", { class: "door-t" }, "Make a plan →"),
          el("span", { class: "door-d" }, "Say what you bring and how much time you have. Get what to read, one thing to do this week, and programs open now.")),
        el("p", { class: "small muted door-note" }, "Have an AI agent? ", link("#/warroom", "Put it to work on a mission with a judge →")))),
    el("section", { class: "frame" },
      el("div", { class: "frame-text" },
        el("h2", { class: "first" }, MAP.frame.title),
        el("p", { class: "lede-s" }, MAP.frame.lede),
        frameQuote(MAP.frame.quotes[1]),
        el("p", { class: "small muted" }, "Insight is understanding the danger and what helps. Technology here is the protective kind, built before what it protects against. Coordination is acting together. ",
          link("#/understand/frame", "More on the frame →"))),
      pathFigure()),
    mapSummary(),
    MAP.axes.map((a) => el("section", { class: `axis axis-${a.id}`, "aria-labelledby": `ax-${a.id}` },
      el("header", { class: "axis-head" },
        el("h2", { id: `ax-${a.id}` }, a.title),
        el("p", { class: "axis-gloss" }, a.gloss),
        axisStats(a)),
      el("div", { class: `map map-${a.regions.length}` }, a.regions.map((rid) => MAP.regions.find((r) => r.id === rid)).map((r) =>
        el("section", { class: "region", "aria-labelledby": `r-${r.id}` },
          el("header", {}, el("span", { class: "rnum", "aria-hidden": "true" }, String(r.n)), el("h3", { id: `r-${r.id}` }, r.title)),
          el("p", { class: "region-sum" }, r.summary),
          el("ul", { class: "needs" }, r.needs.map(needTile))))))),
    el("section", { class: "roadmap-wrap" },
      el("h2", {}, "What the war room itself needs"),
      el("p", { class: "muted" }, "Half the map has no mission yet, because most of AI safety has no automatic judge. This is what would change that, and what has to happen before any result here is announced."),
      el("ol", { class: "roadmap" }, MAP.roadmap.map((x) => el("li", {}, el("b", {}, x.title), el("span", {}, x.text))))),
  ];
}

/* where people disagree: Futuras' placements, as text plus thin bars */
const isPlaced = (r) => r.status !== "declined" && r.value !== null && r.value !== undefined;
const dimOf = (id) => (VIEWS ? VIEWS.dimensions.find((d) => d.id === id) : null);
function dist(dimId, opts = {}) {
  const dim = dimOf(dimId);
  if (!dim) return VIEWS === null ? el("p", { class: "small faint" }, "The map of views (Futuras) is not available right now.") : null;
  const rows = (VIEWS.current[dimId] || []);
  const placed = rows.filter(isPlaced);
  const declined = rows.filter((r) => !isPlaced(r));
  const groups = dim.points.map((pt) => ({ pt, who: placed.filter((r) => r.value === pt.value) }));
  const max = Math.max(1, ...groups.map((g) => g.who.length));
  return el("div", { class: `dist${opts.compact ? " dist-compact" : ""}` },
    el("ul", { class: "dist-rows" }, groups.map(({ pt, who }) => el("li", { title: who.map((r) => r.name).join(", ") || "nobody" },
      el("span", { class: "dist-label" }, opts.compact ? pt.short : pt.label),
      el("span", { class: "hbar", "aria-hidden": "true" }, el("span", { style: `width:${(100 * who.length) / max}%` })),
      el("span", { class: "dist-n" }, String(who.length)),
      opts.names && who.length ? el("span", { class: "dist-names" }, who.map((r) => r.short).join(", ")) : null))),
    el("p", { class: "dist-foot" },
      `${placed.length} placed`, declined.length ? `, ${declined.length} declined to answer` : "",
      opts.link === false ? "" : [" · ", link(`#/question/${dimId}`, "every placement, in their words →")]));
}

function pageNeed(id) {
  if (!MAP) return [el("p", { class: "loading" }, "Loading the map…")];
  const n = MAP.needs[id];
  if (!n) return notFound();
  const r = regionOf(id);
  const st = needStatus(n);
  const ids = allNeedIds();
  const i = ids.indexOf(id);
  const help = (n.theaters || []).map(theaterInfo).filter(Boolean);
  const ax = axisOfRegion(r.id);
  return [
    el("p", { class: "crumbs" }, link("#/", "Map"), ` / ${ax.title} / ${r.n}. ${r.title}`),
    el("div", { class: "page-head" },
      el("div", { class: "pill-row" }, chip(st)),
      el("h1", { class: "h1-need" }, n.title),
      el("p", { class: "lede" }, n.question)),
    el("div", { class: "grid2" },
      el("div", {},
        el("h2", { class: "first" }, "Why it matters"),
        el("p", {}, n.why),
        el("h2", {}, "What is still open"),
        el("ul", { class: "open-list" }, n.open.map((o) => el("li", {}, o))),
        el("h2", {}, "What to read"),
        el("ul", { class: "reading" }, n.texts.map((t) => el("li", {},
          el("div", {}, extLink(t.url, t.title), el("span", { class: "faint" }, ` · ${t.authors}, ${t.year}`)),
          t.note ? el("div", { class: "small muted" }, t.note) : null))),
        whoPanel(id),
        (n.views || []).length ? [
          el("h2", {}, "Where people disagree"),
          el("p", { class: "small muted" }, "Named people placed by their most recent statement on each question, from the Futuras map of views. Hover a row for the names."),
          n.views.map((d) => { const dim = dimOf(d); return el("div", { class: "qblock" },
            el("h3", {}, dim ? link(`#/question/${d}`, dim.question) : d), dist(d, { names: true })); })] : null),
      el("aside", {},
        el("h2", { class: "first" }, "How you can help"),
        help.length ? help.map((h) => el("article", { class: "card help-card" },
          h.judge ? judgeBadge(h.judge) : null,
          el("a", { class: "title", href: h.href }, el("h3", {}, h.title)),
          el("p", { class: "small muted" }, h.line),
          el("p", { class: "small", style: "margin:0" }, link(h.href, h.judge ? "Open the theater →" : "Start →")))) : null,
        st === "none" ? el("div", { class: "note none-note" }, el("b", {}, "No mission yet. "),
          n.judge_needed || "This need has a theater, but it is not set up on this desk.",
          el("p", { class: "small", style: "margin:0.5rem 0 0" }, formLink(judgeUrl(n, id), "Propose a judge →", null))) : null,
        programsFor(id).length ? [el("h3", { class: "who-h" }, "Programs for this need"),
          el("ul", { class: "progs" }, programsFor(id).slice(0, 4).map((pr) => programCard(pr, { brief: true }))),
          el("p", { class: "small" }, link("#/programs", "Every program →"), " · ", link("#/plan", "Make a plan →"))] :
          el("p", { class: "small" }, link("#/plan", "Make a plan to help →")),
        st === "none" || st === "practice" ? el("p", { class: "small muted" }, "Without an agent you can still read, and help review: ", link("#/how", "how review works"), ".") : null,
        n.terms.length ? [el("h2", {}, "The lingo"),
          el("dl", { class: "terms" }, n.terms.filter((t) => MAP.terms[t]).map((t) =>
            [el("dt", {}, MAP.terms[t].term), el("dd", {}, MAP.terms[t].def)])),
          el("p", { class: "small" }, link("#/lingo", "Every term on the map →"))] : null)),
    el("nav", { class: "pager", "aria-label": "Other needs" },
      i > 0 ? link(`#/need/${ids[i - 1]}`, `← ${MAP.needs[ids[i - 1]].title}`) : el("span", {}),
      i < ids.length - 1 ? link(`#/need/${ids[i + 1]}`, `${MAP.needs[ids[i + 1]].title} →`) : el("span", {})),
  ];
}

function whoPanel(id) {
  if (EFFORTS === undefined) return null;
  const head = el("h2", {}, "Who is working on it");
  if (EFFORTS === null) return [head, el("p", { class: "small faint" }, "The record of efforts is not available right now.")];
  const rows = effortsFor(id);
  const ins = instrumentsFor(id);
  if (!rows.length && !ins.length) return [head,
    el("p", { class: "empty" }, "Nobody in the record yet. That may be a gap in the field or a gap in the record."),
    el("p", { class: "small" }, link("#/efforts", "Everyone in the record →"))];
  return [head,
    el("p", { class: "small muted" }, `${rows.length} group${rows.length === 1 ? "" : "s"}${ins.length ? ` and ${ins.length} rule${ins.length === 1 ? "" : "s"} or agreement${ins.length === 1 ? "" : "s"}` : ""} in the record, checked ${EFFORTS.as_of}. Each line links to its source.`),
    rows.length ? el("ul", { class: "who-list" }, rows.map(({ org, efforts }) => el("li", {},
      el("div", { class: "who-org" }, orgLink(org), el("span", { class: "faint" }, ` · ${kindName(org.kind)}`)),
      el("ul", { class: "who-efforts" }, efforts.map((e) => el("li", {},
        extLink(e.url, e.title), e.year ? el("span", { class: "faint" }, ` · ${e.year}`) : null,
        el("div", { class: "small muted" }, e.what))))))) : null,
    ins.length ? [el("h3", { class: "who-h" }, "Rules and agreements"),
      el("ul", { class: "who-efforts who-ins" }, ins.map((i) => el("li", {},
        extLink(i.url, i.name), el("span", { class: "faint" }, ` · ${[i.jurisdiction, yearOf(i.date)].filter(Boolean).join(", ")}`),
        el("div", { class: "small muted" }, i.what))))] : null,
    el("p", { class: "small" }, link("#/efforts", "Everyone in the record →"))];
}

function scrollButton(targetId, text) {
  return el("button", { type: "button", class: "linklike", onclick: () => {
    const t = document.getElementById(targetId);
    if (t) t.scrollIntoView({ behavior: "smooth", block: "start" });
  } }, text);
}

function pageUnderstand() {
  if (!MAP) return [el("p", { class: "loading" }, "Loading…")];
  const groups = VIEWS ? [["expect", "What they expect"], ["want", "What they want"]] : [];
  const nTerms = Object.keys(MAP.terms).length;
  return [
    el("p", { class: "crumbs" }, link("#/", "Map"), " / Understand"),
    el("div", { class: "page-head" },
      el("p", { class: "eyebrow" }, "Understand the debate"),
      el("h1", {}, "The argument about AI risk, step by step"),
      el("p", { class: "lede" }, "For anyone who wants to read the proper texts, learn the lingo and follow the arguments. Each step gives the reason people believe it, the strongest objection, the texts behind both, and where named people stand, in their own words."),
      el("p", { class: "onpage" }, "On this page: ",
        joinWith([scrollButton("steps", "The case in seven steps"), scrollButton("frame", "What it would take"),
          scrollButton("disagree", "Where people disagree"), scrollButton("read", "What to read"), link("#/futures", "How the future could go"),
          link("#/lingo", `The lingo (${nTerms} terms)`)], " · "))),
    el("h2", { id: "steps" }, "The case in seven steps"),
    el("p", { class: "muted" }, "Each step depends on the ones before it. Many people accept some steps and reject others; the step someone rejects is usually their crux."),
    el("ol", { class: "argument" }, MAP.argument.map((a, k) => el("li", { class: "step-card" },
      el("div", { class: "step-n", "aria-hidden": "true" }, String(k + 1)),
      el("div", { class: "step-body" },
        el("h3", {}, a.claim),
        el("div", { class: "proscons" },
          el("p", {}, el("b", {}, "Why people believe it. "), a.for),
          el("p", {}, el("b", {}, "The strongest objection. "), a.against)),
        el("p", { class: "small" }, "Read: ", joinWith(a.texts.map((t) => [extLink(t.url, t.title), el("span", { class: "faint" }, ` (${t.authors}, ${t.year})`)]), "; ")),
        a.view && dimOf(a.view) ? el("div", { class: "step-view" },
          el("p", { class: "small step-q" }, "Where people stand: ", link(`#/question/${a.view}`, dimOf(a.view).question)),
          dist(a.view, { names: true, compact: true, link: false })) : null,
        el("p", { class: "small faint" }, "On the map: ", joinWith(a.needs.map(needLink))))))),
    el("h2", { id: "frame" }, "What it would take: ", MAP.frame.title.toLowerCase()),
    el("div", { class: "frame frame-full" },
      el("div", { class: "frame-text" },
        el("p", { class: "lede-s" }, MAP.frame.lede),
        MAP.frame.body.map((p) => el("p", {}, p)),
        MAP.frame.quotes.map(frameQuote)),
      pathFigure()),
    el("div", { class: "axis-cards" }, MAP.axes.map((a) => el("article", { class: "card" },
      el("h3", {}, a.title),
      el("p", { class: "small faint" }, `Bostrom: “${a.bostrom}”`),
      el("p", { class: "small" }, a.gloss),
      el("p", { class: "small" }, "On the map: ", joinWith(a.regions.map((rid) => MAP.regions.find((r) => r.id === rid).title)), " · ",
        link(`#/map/${a.id}`, "see the needs →"))))),
    el("p", { class: "small muted" }, MAP.frame.caveat, " Sources: ",
      joinWith(MAP.frame.sources.map((s) => [extLink(s.url, s.title), ` (${s.authors}, ${s.year})`]), "; "), "."),
    el("h2", { id: "disagree" }, "Where people disagree"),
    VIEWS ? el("p", { class: "muted" }, `Ten questions from the Futuras map of views: ${VIEWS.counts.people} people and groups, ${VIEWS.counts.statements} statements, ${VIEWS.counts.placements} placements, as of ${VIEWS.as_of}. Each person is placed by their most recent statement on the question, and every placement shows the passage it was coded from.`)
      : el("p", { class: "muted" }, "The Futuras map of views is not available right now."),
    groups.map(([g, title]) => [el("h3", { class: "group-h" }, title),
      el("div", { class: "qgrid" }, VIEWS.dimensions.filter((d) => d.group === g).map((d) =>
        el("article", { class: "card qcard" },
          el("a", { class: "title", href: `#/question/${d.id}` }, el("h3", {}, d.question)),
          dist(d.id, { compact: true }))))]),
    el("h2", { id: "read" }, "What to read"),
    el("div", { class: "reading-levels" }, MAP.reading.map((lv) => el("section", { class: "card" },
      el("h3", {}, lv.level), el("p", { class: "small muted" }, lv.hint),
      el("ol", { class: "reading" }, lv.items.map((t) => el("li", {},
        el("div", {}, extLink(t.url, t.title), el("span", { class: "faint" }, ` · ${t.authors}, ${t.year}`)),
        t.note ? el("div", { class: "small muted" }, t.note) : null)))))),
    el("h2", {}, "Then help"),
    el("div", { class: "prose" },
      el("p", {}, "The quickest way to learn a debate is to help keep its record honest. The ", link("#/intel", "intelligence desk"),
        " keeps the map of who believes what current: an agent finds what someone has said since the last statement on record and codes it, every quote is checked against its page, and a person reviews the coding before it counts."),
      el("p", {}, "If you have an AI agent, ", link("#/warroom", "put it to work"), ". Every need on ", link("#/", "the map"), " says whether there is a mission for it yet.")),
  ];
}

function pageQuestion(id) {
  if (VIEWS === undefined) return [el("p", { class: "loading" }, "Loading…")];
  if (VIEWS === null) return [el("div", { class: "page-head", style: "margin-top:2rem" }, el("h1", {}, "Map of views unavailable"),
    el("p", {}, "The desk could not read the Futuras map of views. ", link("#/understand", "Back to Understand")))];
  const dim = dimOf(id);
  if (!dim) return notFound();
  const rows = VIEWS.current[id] || [];
  const placed = rows.filter(isPlaced);
  const declined = rows.filter((r) => !isPlaced(r));
  const unplaced = Object.entries(VIEWS.people).filter(([pid]) => !rows.some((r) => r.person === pid)).map(([, p]) => p.short).sort();
  const needs = MAP ? allNeedIds().filter((n) => (MAP.needs[n].views || []).includes(id)) : [];
  const placement = (r) => el("li", { class: "placement" },
    el("div", { class: "pl-head" }, el("b", {}, r.name), el("span", { class: "when" }, r.date)),
    el("p", {}, r.summary),
    r.condition ? el("p", { class: "small muted" }, `Condition: ${r.condition}`) : null,
    r.evidence ? el("blockquote", {}, r.evidence) : null,
    el("p", { class: "small faint" }, "From ", extLink(r.url, r.title || r.url || "source"), r.publisher ? ` (${r.publisher})` : ""));
  return [
    el("p", { class: "crumbs" }, link("#/understand", "Understand"), " / Where people disagree / ", dim.short),
    el("div", { class: "page-head" },
      el("p", { class: "eyebrow" }, dim.group === "expect" ? "What they expect" : "What they want"),
      el("h1", { class: "h1-need" }, dim.question),
      dim.note ? el("p", { class: "muted" }, dim.note) : null),
    dist(id, { names: true, link: false }),
    dim.points.map((pt) => {
      const who = placed.filter((r) => r.value === pt.value);
      return el("section", {},
        el("h2", {}, pt.label, el("span", { class: "faint" }, ` · ${who.length}`)),
        who.length ? el("ul", { class: "placements" }, who.map(placement)) : el("p", { class: "empty" }, "Nobody on the map is placed here."));
    }),
    declined.length ? [el("h2", {}, "Declined to answer"), el("ul", { class: "placements" }, declined.map(placement))] : null,
    unplaced.length ? el("p", { class: "small muted" }, `No statement on record addresses this question for: ${unplaced.join(", ")}.`) : null,
    el("p", { class: "note small" }, "Placements are Futuras' coding of what each person wrote, not a verdict on who is right. Every placement carries the passage it was coded from and the page it is on, and Futuras' checker compares each passage with its page. A person's placement is their most recent statement on the question; earlier ones are in Futuras."),
    needs.length ? el("p", { class: "small" }, "On the map: ", joinWith(needs.map(needLink))) : null,
  ];
}

/* ---------- programs (site/programs.json) and the plan ---------- */
const PROG_KINDS = { course: ["Courses", "Course"], fellowship: ["Fellowships", "Fellowship"], bootcamp: ["Bootcamps", "Bootcamp"],
  grant: ["Grants", "Grant"], event: ["Events", "Event"], "job-board": ["Job boards", "Job board"], advising: ["Advising", "Advising"], community: ["Communities", "Community"] };
const progKind = (k, plural) => (PROG_KINDS[k] ? PROG_KINDS[k][plural ? 0 : 1] : k);
const todayIso = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
function fmtDate(iso) {
  if (!iso) return "";
  const parts = iso.split("-").map(Number);
  const d = new Date(parts[0], (parts[1] || 1) - 1, parts[2] || 1);
  return d.toLocaleDateString(undefined, parts.length === 3 ? { day: "numeric", month: "short", year: "numeric" } : { month: "short", year: "numeric" });
}
/* status is worked out against today's date, so a stale "open" turns into "closed" by itself */
function progStatus(p) {
  const d = p.dates || {};
  const t = todayIso();
  if (p.kind === "event" && d.starts && d.starts < t && (!d.deadline || d.deadline < t)) return { key: "closed", label: "Took place", sort: "z" };
  if (d.deadline && d.deadline >= t) return { key: "open", label: `Apply by ${fmtDate(d.deadline)}`, sort: `1${d.deadline}` };
  if (d.opens && d.opens > t) return { key: "upcoming", label: `Opens ${fmtDate(d.opens)}`, sort: `2${d.opens}` };
  if (p.kind === "event" && d.starts && d.starts >= t) return { key: "upcoming", label: `Starts ${fmtDate(d.starts)}`, sort: `2${d.starts}` };
  if (d.status === "rolling") return { key: "rolling", label: "Rolling", sort: "3" };
  if (d.status === "open" && !d.deadline) return { key: "open", label: "Open now", sort: "19" };
  if (d.deadline && d.deadline < t) return { key: "closed", label: `Closed ${fmtDate(d.deadline)}`, sort: "z" };
  if (d.status === "closed") return { key: "closed", label: "Closed for now", sort: "z" };
  return { key: "unknown", label: "Dates not announced", sort: "y" };
}
const PCHIP_TIP = {
  open: "Taking applications now. Dates come from the program's own page; check there before you apply.",
  upcoming: "Not open yet: this is when applications open or the event starts.",
  rolling: "Applications are accepted at any time.",
  closed: "Closed for now. The program's page says whether there will be another round.",
  unknown: "The program has not announced dates for its next round.",
};
const statusChip = (s) => el("span", { class: `pchip pchip-${s.key}`, title: PCHIP_TIP[s.key] }, s.label);
const byStatus = (a, b) => progStatus(a).sort.localeCompare(progStatus(b).sort) || a.name.localeCompare(b.name);
function programCard(p, opts = {}) {
  const s = progStatus(p);
  const pickBox = opts.pick && s.key !== "closed" ? el("label", { class: "pick", title: "Add this program to your plan, with a countdown to its deadline" },
    el("input", { type: "checkbox", checked: PICKED.has(p.id), onchange: (e) => { if (e.target.checked) PICKED.add(p.id); else PICKED.delete(p.id); } }),
    " I’ll apply") : null;
  return el("li", { class: `prog prog-${s.key}`, "data-kind": p.kind, "data-for": (p.for || []).join(" "), "data-status": s.key,
    "data-online": /online|remote|virtual/i.test(p.format || "") ? "1" : "0",
    "data-text": `${p.name} ${p.org} ${p.what} ${p.format || ""}`.toLowerCase() },
    el("div", { class: "prog-head" }, extLink(p.url, p.name), statusChip(s)),
    el("p", { class: "small faint prog-meta" }, [progKind(p.kind), p.org && p.org !== p.name ? p.org : "", p.format, p.length, p.commitment, p.pay].filter(Boolean).join(" · ")),
    opts.brief ? null : el("p", { class: "small" }, p.what),
    !opts.brief && p.dates && p.dates.note ? el("p", { class: "small muted" }, p.dates.note) : null,
    pickBox);
}
function programsFor(needId) {
  return PROGRAMS ? PROGRAMS.programs.filter((p) => (p.needs || []).includes(needId) && progStatus(p).key !== "closed").sort(byStatus) : [];
}

const PLAN = { bg: "", t: "", a: "", agent: "" };
const PICKED = new Set();   /* programs ticked "I'll apply" before accepting */
function readPlan(arg) {
  const q = new URLSearchParams(arg || "");
  PLAN.bg = q.get("bg") || ""; PLAN.t = q.get("t") || ""; PLAN.a = q.get("a") || ""; PLAN.agent = q.get("agent") || "";
}
const planQuery = () => new URLSearchParams(Object.entries({ bg: PLAN.bg, t: PLAN.t, a: PLAN.a, agent: PLAN.agent }).filter(([, v]) => v)).toString();
function textByTitle(title) {
  for (const n of Object.values(MAP.needs)) { const t = n.texts.find((x) => x.title === title); if (t) return t; }
  for (const lv of MAP.reading) { const t = lv.items.find((x) => x.title === title); if (t) return t; }
  return null;
}
function choiceGroup(name, legend, options, onPick) {
  return el("fieldset", { class: "choices" }, el("legend", {}, legend),
    el("div", { class: "choice-row" }, options.map(([v, label, hint]) => el("label", { class: "choice" },
      el("input", { type: "radio", name, value: v, checked: PLAN[name] === v, onchange: () => onPick(v) }),
      el("span", { class: "choice-l" }, label), hint ? el("span", { class: "choice-h" }, hint) : null))));
}
/* everything a plan is made of, from the current answers */
function planData() {
  const P = MAP.plan;
  const bg = P.backgrounds.find((b) => b.id === PLAN.bg);
  const tm = P.times.find((x) => x.id === PLAN.t);
  if (!bg || !tm) return null;
  const axis = MAP.axes.find((x) => x.id === PLAN.a);
  const axisIds = axis ? axisNeeds(axis) : null;
  let needs = bg.needs.filter((n) => !axisIds || axisIds.includes(n));
  if (axisIds && needs.length < 2) needs = [...needs, ...axisIds.filter((n) => !needs.includes(n))].slice(0, 4);
  const reads = bg.read.map(textByTitle).filter(Boolean).slice(0, PLAN.t === "taste" ? 2 : 3);
  const fits = PROGRAMS ? PROGRAMS.programs.filter((p) =>
    ((p.for || []).includes(PLAN.bg) || (p.for || []).includes("other")) && (p.time || []).includes(PLAN.t) &&
    !["advising", "community", "job-board"].includes(p.kind) && progStatus(p).key !== "closed" &&
    (!axisIds || !(p.needs || []).length || p.needs.some((n) => axisIds.includes(n)))).sort(byStatus) : [];
  const talk = PROGRAMS ? PROGRAMS.programs.filter((p) => ["advising", "community", "job-board"].includes(p.kind) &&
    ((p.for || []).includes(PLAN.bg) || (p.for || []).includes("other"))).sort(byStatus).slice(0, 3) : [];
  const orgs = [...new Map(needs.flatMap((n) => effortsFor(n).map((x) => [x.org.id, x.org]))).values()]
    .filter((o) => PLAN.bg === "policy" ? ["government", "policy", "watchdog"].includes(o.kind) : PLAN.bg === "media" ? ["watchdog", "research", "policy"].includes(o.kind) : true)
    .slice(0, 10);
  const summary = `For someone ${bg.who}, with ${PLAN.t === "career" ? "a career change in mind" : tm.label.toLowerCase()}${axis ? `, drawn to ${axis.title.toLowerCase()}` : ""}.`;
  return { bg, tm, axis, needs, reads, fits, talk, orgs, summary };
}
function planOutput() {
  const d = planData();
  if (!d) return el("p", { class: "empty" }, "Pick what you bring and how much time you have, and your plan appears here.");
  const { bg, needs, reads, fits, talk, orgs } = d;
  const shown = PLAN.t === "taste" ? 3 : 6;
  let n = 0;
  const step = (title, ...body) => el("li", { class: "plan-step" }, el("div", { class: "plan-n", "aria-hidden": "true" }, String(++n)), el("div", {}, el("h3", {}, title), body));
  return el("section", { class: "plan", "aria-live": "polite" },
    el("h2", { class: "first" }, "Your plan"),
    el("p", { class: "muted" }, d.summary),
    el("ol", { class: "plan-steps" },
      step(PLAN.t === "taste" ? "Read, this afternoon" : "Read, this week",
        el("ul", { class: "reading" }, reads.map((t) => el("li", {}, el("div", {}, extLink(t.url, t.title), el("span", { class: "faint" }, ` · ${t.authors}, ${t.year}`)),
          t.note ? el("div", { class: "small muted" }, t.note) : null))),
        el("p", { class: "small" }, "Then ", link("#/understand", "the case in seven steps"), ", with the strongest objection to each.")),
      step("Do one thing", el("p", {}, bg.first),
        PLAN.agent === "yes" ? el("div", { class: "plan-agent" }, el("p", { class: "small" }, "Your agent can start now. Paste this into it:"),
          el("div", { class: "copyline" }, el("code", {}, joinLine()), copyButton(joinLine))) :
          el("p", { class: "small muted" }, "Have an AI agent that can run code? ", link("#/warroom", "Put it to work"), " on a mission with a judge.")),
      PLAN.t === "taste" ? null : step(fits.length ? "Apply" : "Apply when something opens",
        !PROGRAMS ? el("p", { class: "small faint" }, "The list of programs is not available right now.") :
        fits.length ? [el("p", { class: "small muted" }, "Tick the ones you will apply to. When you accept the plan, each gets a countdown to its own deadline."),
          el("ul", { class: "progs" }, fits.slice(0, shown).map((p) => programCard(p, { brief: true, pick: true }))),
          el("p", { class: "small" }, link(`#/programs/for=${PLAN.bg}`, `All ${fits.length} programs that fit, with details →`))]
          : el("p", { class: "small" }, "Nothing that fits is open right now. ", link("#/programs", "See every program"), " and when it opens.")),
      step("Where your skills are used",
        el("ul", { class: "needs plan-needs" }, needs.map(needTile)),
        orgs.length ? el("p", { class: "small" }, "Groups working on these: ", joinWith(orgs.map(orgLink)), ".") : null),
      talk.length ? step("Talk to someone",
        el("ul", { class: "progs" }, talk.map((p) => programCard(p, { brief: true })))) : null),
    el("div", { class: "accept" },
      el("button", { type: "button", class: "btn-primary", onclick: () => acceptPlan(d) }, ACTIVE ? "Accept this plan instead" : "Accept this plan and start the clock"),
      el("span", { class: "small muted" }, `Each step gets a due date (${planDaysText()}), and programs you tick count down to their real deadlines. Saved only in this browser.`)),
    el("div", { class: "plan-foot" },
      el("span", { class: "small muted" }, "This plan has its own link, so you can come back to it or send it to someone. "),
      copyButton(() => `${location.href.split("#")[0]}#/plan/${planQuery()}`, "Copy link")),
    PROGRAMS ? el("p", { class: "small faint" }, `Program dates checked ${PROGRAMS.as_of}. Dates change; confirm on each program's page.`) : null);
}

/* ---------- an accepted plan: dated steps and a countdown, kept only in this browser ---------- */
const PLAN_KEY = "rfd.plan.v1";
const DAY = 86400000;
const PLAN_DAYS = { taste: { read: 1, do: 3, apply: 7, talk: 7 }, week: { read: 7, do: 14, apply: 14, talk: 21 }, career: { read: 3, do: 7, apply: 7, talk: 14 } };
const planDaysText = () => { const x = PLAN_DAYS[PLAN.t] || PLAN_DAYS.week; return `read within ${x.read} day${x.read === 1 ? "" : "s"}, your first task within ${x.do}`; };
function loadActive() {
  try { const v = JSON.parse(localStorage.getItem(PLAN_KEY) || "null"); return v && Array.isArray(v.items) ? v : null; } catch { return null; }
}
function saveActive(v) {
  try { if (v) localStorage.setItem(PLAN_KEY, JSON.stringify(v)); else localStorage.removeItem(PLAN_KEY); return true; } catch { return false; }
}
let ACTIVE = loadActive();
let SAVE_FAILED = false;
const endOfDay = (iso) => { const [y, m, d] = iso.split("-").map(Number); return new Date(y, m - 1, d, 23, 59, 0).getTime(); };
function buildActive(d, now = Date.now()) {
  const days = PLAN_DAYS[PLAN.t];
  const items = [
    { id: "read", kind: "read", title: d.reads.length === 1 ? "Read one text" : `Read ${d.reads.length} texts`,
      links: d.reads.map((t) => ({ title: t.title, url: t.url })), due: now + days.read * DAY },
    { id: "do", kind: "do", title: "Do one thing", detail: d.bg.first, due: now + days.do * DAY },
  ];
  if (PLAN.t !== "taste") {
    const chosen = d.fits.filter((p) => PICKED.has(p.id));
    for (const p of chosen) {
      const dl = p.dates && p.dates.deadline;
      items.push({ id: `apply:${p.id}`, kind: "apply", title: `Apply to ${p.name}`, url: p.url,
        detail: dl ? `Deadline ${fmtDate(dl)}, in the program's own time zone: check its page.` : "No deadline published; this is a date to aim for.",
        due: dl ? endOfDay(dl) : now + days.apply * DAY });
    }
    if (!chosen.length) items.push({ id: "apply", kind: "apply", title: "Choose a program and apply", href: `#/programs/for=${PLAN.bg}`,
      detail: "Pick one from the programs that fit your plan.", due: now + days.apply * DAY });
  }
  if (d.talk.length) items.push({ id: "talk", kind: "talk", title: "Talk to someone", links: d.talk.map((p) => ({ title: p.name, url: p.url })), due: now + days.talk * DAY });
  items.sort((a, b) => a.due - b.due);
  return { v: 1, accepted: now, query: planQuery(), summary: d.summary, items: items.map((i) => ({ ...i, done: null })) };
}
function acceptPlan(d) {
  if (ACTIVE && ACTIVE.items.some((i) => !i.done) && !window.confirm("Replace the plan you accepted earlier? Its countdown and ticks will be lost.")) return;
  ACTIVE = buildActive(d);
  SAVE_FAILED = !saveActive(ACTIVE);
  PICKED.clear();
  render();
  window.scrollTo({ top: 0, behavior: "smooth" });
}
function timeLeft(ms) {
  const s = Math.abs(ms) / 1000;
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60);
  const t = d >= 1 ? `${d} day${d === 1 ? "" : "s"} ${h} h` : h >= 1 ? `${h} h ${m} min` : `${m} min ${String(sec).padStart(2, "0")} s`;
  return ms < 0 ? `${t} overdue` : `${t} left`;
}
const fmtWhen = (ms) => new Date(ms).toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
const countdown = (due, cls) => el("span", { class: `cd ${cls || ""}${due < Date.now() ? " overdue" : ""}`, "data-due": String(due),
  title: `${due < Date.now() ? "Past due since" : "Time left until"} ${new Date(due).toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" })}` }, timeLeft(due - Date.now()));
/* one ticker for every countdown on the page, the planbar included */
setInterval(() => {
  const now = Date.now();
  document.querySelectorAll("[data-due]").forEach((n) => {
    const due = Number(n.dataset.due);
    n.textContent = timeLeft(due - now);
    n.classList.toggle("overdue", due < now);
  });
}, 1000);
function icsText(A) {
  const stamp = (ms) => new Date(ms).toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
  const esc = (s) => String(s).replace(/\\/g, "\\\\").replace(/;/g, "\;").replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");
  const fold = (line) => { const out = []; let rest = line; while (rest.length > 73) { out.push(rest.slice(0, 73)); rest = " " + rest.slice(73); } out.push(rest); return out.join("\r\n"); };
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Report for Duty//Plan//EN", "CALSCALE:GREGORIAN", "X-WR-CALNAME:My AI safety plan"];
  for (const i of A.items) {
    const desc = [i.detail, ...(i.links || []).map((l) => `${l.title}: ${l.url}`), i.url].filter(Boolean).join("\n");
    lines.push("BEGIN:VEVENT", `UID:${A.accepted}-${i.id.replace(/[^a-z0-9-]/gi, "-")}@reportforduty`, `DTSTAMP:${stamp(Date.now())}`,
      `DTSTART:${stamp(i.due - 30 * 60000)}`, `DTEND:${stamp(i.due)}`, `SUMMARY:${esc(i.title)}`, `DESCRIPTION:${esc(desc)}`);
    if (i.url) lines.push(`URL:${i.url}`);
    lines.push("BEGIN:VALARM", "ACTION:DISPLAY", `DESCRIPTION:${esc(i.title)}`, "TRIGGER:-P1D", "END:VALARM", "END:VEVENT");
  }
  lines.push("END:VCALENDAR");
  return lines.map(fold).join("\r\n") + "\r\n";
}
function downloadIcs() {
  const url = URL.createObjectURL(new Blob([icsText(ACTIVE)], { type: "text/calendar" }));
  const a = el("a", { href: url, download: "my-ai-safety-plan.ics" });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
function setDone(item, on) {
  item.done = on ? Date.now() : null;
  SAVE_FAILED = !saveActive(ACTIVE);
  render();
}
function activeView() {
  const A = ACTIVE;
  const now = Date.now();
  const next = A.items.find((i) => !i.done);
  const done = A.items.filter((i) => i.done).length;
  const lastDue = Math.max(...A.items.map((i) => i.due));
  const dayN = Math.max(1, Math.floor((now - A.accepted) / DAY) + 1);
  const span = Math.max(1, Math.ceil((lastDue - A.accepted) / DAY));
  return el("section", { class: `active-plan${next ? "" : " complete"}`, "aria-labelledby": "ap-h" },
    el("div", { class: "ap-head" },
      el("h2", { id: "ap-h", class: "first" }, next ? "Your plan is running" : "Plan complete"),
      el("p", { class: "small muted" }, `Accepted ${fmtWhen(A.accepted)} · day ${Math.min(dayN, span)} of ${span} · ${done} of ${A.items.length} steps done`)),
    el("p", { class: "small muted" }, A.summary),
    next ? el("div", { class: "countdown" },
      el("span", { class: "cd-k" }, "Next"),
      el("span", { class: "cd-title" }, next.title),
      countdown(next.due, "cd-big"),
      el("span", { class: "small faint" }, `Due ${fmtWhen(next.due)}`))
      : el("div", { class: "countdown" }, el("span", { class: "cd-title" }, "Every step is done."),
          el("span", { class: "small muted" }, "Make a bigger plan below, or take on a need with no mission yet.")),
    el("div", { class: "hbar ap-bar", role: "img", "aria-label": `${done} of ${A.items.length} steps done` },
      el("span", { style: `width:${(100 * done) / A.items.length}%` })),
    el("ol", { class: "ap-items" }, A.items.map((i) => el("li", { class: `ap-item${i.done ? " is-done" : ""}` },
      el("label", { class: "ap-check" },
        el("input", { type: "checkbox", checked: !!i.done, onchange: (e) => setDone(i, e.target.checked) }),
        el("span", { class: "ap-title" }, i.title)),
      i.done ? el("span", { class: "ap-when small faint" }, `Done ${fmtWhen(i.done)}`) : countdown(i.due, "ap-when small"),
      el("div", { class: "small muted ap-detail" },
        i.links ? joinWith(i.links.map((l) => extLink(l.url, l.title)), " · ") : i.detail,
        i.links && i.detail ? [" ", i.detail] : null,
        i.url ? [" ", extLink(i.url, "Program page →")] : null,
        i.href ? [" ", link(i.href, "Programs →")] : null)))),
    el("div", { class: "ap-actions" },
      el("button", { type: "button", onclick: downloadIcs }, "Add to my calendar"),
      link(`#/plan/${A.query}`, "See the full plan"),
      el("button", { type: "button", class: "linklike", onclick: () => {
        if (!window.confirm("Drop this plan? Its countdown and ticks will be deleted from this browser.")) return;
        ACTIVE = null; saveActive(null); render();
      } }, "Drop this plan")),
    SAVE_FAILED ? el("p", { class: "note small" }, "This browser would not save the plan, so it will be gone when you leave. Add it to your calendar to keep the dates.")
      : el("p", { class: "small faint" }, "Saved only in this browser; nothing is sent to the desk. The calendar file has a reminder a day before each step."));
}
function updatePlanbar(head) {
  const bar = document.getElementById("planbar");
  if (!bar) return;
  const next = ACTIVE ? ACTIVE.items.find((i) => !i.done) : null;
  if (!next || head === "plan") { bar.hidden = true; bar.replaceChildren(); return; }
  bar.hidden = false;
  bar.replaceChildren(el("div", { class: "wrap planbar-in" },
    el("a", { href: "#/plan", title: "Your plan’s next step and the time left. Kept only in this browser." }, el("span", { class: "pb-k" }, "Your plan"), el("span", { class: "pb-t" }, `Next: ${next.title}`)),
    countdown(next.due, "pb-cd")));
}
window.addEventListener("storage", (e) => { if (e.key === PLAN_KEY) { ACTIVE = loadActive(); render(); } });

function pagePlan(arg) {
  if (!MAP) return [el("p", { class: "loading" }, "Loading…")];
  readPlan(arg);
  const out = el("div", {}, planOutput());
  const pick = (k) => (v) => {
    const wasReady = !!(PLAN.bg && PLAN.t);
    PLAN[k] = v;
    history.replaceState(null, "", `#/plan/${planQuery()}`);
    out.replaceChildren(planOutput());
    /* on a phone the plan is below the questions: show it once it first appears */
    if (!wasReady && PLAN.bg && PLAN.t && window.innerWidth < 860) out.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  const P = MAP.plan;
  return [
    el("p", { class: "crumbs" }, link("#/", "Map"), " / Get involved"),
    ACTIVE ? activeView() : null,
    el("div", { class: "page-head" },
      el("p", { class: "eyebrow" }, "Get involved"),
      el(ACTIVE ? "h2" : "h1", {}, ACTIVE ? "Make a different plan" : "Make a plan to help"),
      el("p", { class: "lede" }, P.intro)),
    el("div", { class: "plan-grid" },
      el("form", { class: "plan-form", onsubmit: (e) => e.preventDefault() },
        choiceGroup("bg", "What do you bring?", P.backgrounds.map((b) => [b.id, b.label]), pick("bg")),
        choiceGroup("t", "How much time?", P.times.map((x) => [x.id, x.label, x.hint]), pick("t")),
        choiceGroup("a", "What pulls you in? (optional)", [...MAP.axes.map((x) => [x.id, x.title]), ["", "Not sure yet"]], pick("a")),
        choiceGroup("agent", "Do you have an AI agent that can run code?", [["yes", "Yes"], ["", "No, or not sure"]], pick("agent"))),
      out),
  ];
}

const PROG_FILTER = { kind: "", for: "", open: false, online: false, q: "" };
function pagePrograms(arg) {
  if (PROGRAMS === undefined) return [el("p", { class: "loading" }, "Loading…")];
  if (!PROGRAMS || !MAP) return [el("div", { class: "page-head", style: "margin-top:2rem" }, el("h1", {}, "Programs unavailable"),
    el("p", {}, "The list of programs could not be loaded. ", link("#/", "Back to the map")))];
  const q = new URLSearchParams(arg || "");
  if (q.has("for")) PROG_FILTER.for = q.get("for");
  const list = [...PROGRAMS.programs].sort(byStatus);
  const ul = el("ul", { class: "progs progs-full" }, list.map((p) => programCard(p)));
  const count = el("p", { class: "small faint", "aria-live": "polite" });
  const apply = () => {
    let shown = 0;
    ul.querySelectorAll(".prog").forEach((li) => {
      const f = li.dataset.for.split(" ");
      const hide = (PROG_FILTER.kind && li.dataset.kind !== PROG_FILTER.kind) ||
        (PROG_FILTER.for && !f.includes(PROG_FILTER.for) && !f.includes("other")) ||
        (PROG_FILTER.open && !["open", "rolling"].includes(li.dataset.status)) ||
        (PROG_FILTER.online && li.dataset.online !== "1") || (PROG_FILTER.q && !li.dataset.text.includes(PROG_FILTER.q));
      li.hidden = !!hide;
      if (!hide) shown++;
    });
    count.textContent = `${shown} of ${list.length} shown`;
    bar.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.kind === PROG_FILTER.kind)));
  };
  const kinds = Object.keys(PROG_KINDS).filter((k) => list.some((p) => p.kind === k));
  const bar = el("div", { class: "kind-bar", role: "group", "aria-label": "Show only" },
    [["", "Everything"], ...kinds.map((k) => [k, progKind(k, true)])].map(([k, label]) =>
      el("button", { type: "button", "data-kind": k, onclick: () => { PROG_FILTER.kind = k; apply(); } },
        label, el("span", { class: "faint" }, ` ${k ? list.filter((p) => p.kind === k).length : list.length}`))));
  const sel = el("select", { class: "filter filter-sel", "aria-label": "Suits people with" },
    el("option", { value: "" }, "Any background"), MAP.plan.backgrounds.map((b) => el("option", { value: b.id, selected: PROG_FILTER.for === b.id }, b.label)));
  sel.addEventListener("change", () => { PROG_FILTER.for = sel.value; apply(); });
  const BOX_TIP = { open: "Only programs taking applications today", online: "Only programs you can do remotely" };
  const box = (key, label) => { const i = el("input", { type: "checkbox", checked: PROG_FILTER[key] }); i.addEventListener("change", () => { PROG_FILTER[key] = i.checked; apply(); });
    return el("label", { class: "check", title: BOX_TIP[key] }, i, ` ${label}`); };
  const input = el("input", { type: "search", class: "filter", placeholder: "Filter by name", "aria-label": "Filter programs", value: PROG_FILTER.q });
  input.addEventListener("input", () => { PROG_FILTER.q = input.value.trim().toLowerCase(); apply(); });
  apply();
  const openNow = list.filter((p) => progStatus(p).key === "open").length;
  return [
    el("p", { class: "crumbs" }, link("#/", "Map"), " / ", link("#/plan", "Get involved"), " / Programs"),
    el("div", { class: "page-head" },
      el("p", { class: "eyebrow" }, "Get involved"),
      el("h1", {}, "Programs, grants and events"),
      el("p", { class: "lede" }, `${list.length} ways in: courses, fellowships, grants, events and places to talk to people. ${openNow} take applications now. Sorted by deadline; the status is worked out from today's date.`),
      el("p", { class: "small" }, "Not sure where to start? ", link("#/plan", "Make a plan"), " first.")),
    el("p", { class: "note small" }, el("b", {}, "How this was compiled. "), PROGRAMS.method),
    bar,
    el("div", { class: "filter-row" }, sel, box("open", "Open now"), box("online", "Online"), input),
    count, ul,
  ];
}

/* ---------- prizes on missions (from /api/state) and supporting the project (site/support.json) ---------- */
function money(amount, currency) {
  try { return new Intl.NumberFormat(undefined, { style: "currency", currency, maximumFractionDigits: amount % 1 ? 2 : 0 }).format(amount); }
  catch { return `${amount} ${currency}`; }
}
const allPrizes = () => (STATE && STATE.prizes ? STATE.prizes.prizes : []);
const activePrizes = (target) => allPrizes().filter((p) => p.status === "active" && (!target || p.target === target));
function totalsText(list) {
  const by = {};
  for (const p of list) by[p.currency] = (by[p.currency] || 0) + p.amount;
  return Object.entries(by).map(([c, a]) => money(a, c)).join(" + ");
}
function prizeTag(target) {
  const list = activePrizes(target);
  return list.length ? el("a", { class: "prize-tag", href: "#/prizes", title: `${list.length} prize${list.length === 1 ? "" : "s"} on ${target}` }, `★ ${totalsText(list)}`) : null;
}
function prizeCondition(p) {
  if (p.theater === "audit") return `the first valid verdict on audit model ${p.target}`;
  if (p.theater === "wargame") return `the first exploit of treaty regime ${p.target}`;
  return `the first certified bound of ${pct(p.threshold, 3)} or more on ${p.target}`;
}
function prizeBox(target) {
  const list = allPrizes().filter((p) => p.target === target && p.status !== "expired");
  if (!list.length) return null;
  return el("div", { class: "prize-box" }, list.map((p) => el("p", {},
    el("b", {}, `★ ${money(p.amount, p.currency)} `), p.status === "active" ? `for ${prizeCondition(p)}, until ${fmtDate(p.expires)}. ` :
      `won by `, p.status !== "active" ? [handleLink(p.winner.handle), p.status === "paid" ? " (paid). " : " (awaiting payment). "] : null,
    "Sponsored by ", p.sponsor_url ? extLink(p.sponsor_url, p.sponsor) : p.sponsor, ". ", link("#/prizes", "How prizes work"))));
}
const missionHrefFor = (p) => p.theater === "audit" ? `#/audit/${p.target}` : p.theater === "wargame" ? `#/wargame/${p.target}` : `#/target/${p.target}`;
function prizeRow(p) {
  return el("tr", {},
    el("td", { class: "num" }, el("b", {}, money(p.amount, p.currency))),
    el("td", {}, link(missionHrefFor(p), p.target), el("div", { class: "small muted" }, `For ${prizeCondition(p)}`)),
    el("td", {}, p.sponsor_url ? extLink(p.sponsor_url, p.sponsor) : p.sponsor, el("div", { class: "small faint" }, p.terms)),
    el("td", { class: "small" }, p.status === "active" ? [`Until ${fmtDate(p.expires)}`, el("div", {}, countdown(new Date(`${p.expires}T23:59:59Z`).getTime(), "small"))] :
      p.status === "expired" ? `Expired ${fmtDate(p.expires)}` : ["Won by ", handleLink(p.winner.handle), p.status === "paid" ? ", paid" : ", awaiting payment"]));
}
function prizeTable(list, empty) {
  if (!list.length) return el("p", { class: "empty" }, empty);
  return el("div", { class: "table-wrap" }, el("table", {},
    el("thead", {}, el("tr", {}, el("th", { class: "num" }, "Prize"), el("th", {}, "Mission"), el("th", {}, "Sponsor and how they pay"), el("th", {}, "Status"))),
    el("tbody", {}, list.map(prizeRow))));
}
const isoIn = (days) => { const d = new Date(); d.setDate(d.getDate() + days); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
function pledgeForm() {
  const s = STATE;
  const audits = s.audits ? s.audits.targets.filter((t) => !t.verdict).map((t) => [t.id, `Audit model ${t.id}: first valid verdict`]) : [];
  const regimes = s.wargames ? s.wargames.targets.filter((t) => t.status !== "exploited").map((t) => [t.id, `Treaty regime ${t.id}: first exploit (${t.name})`]) : [];
  const rules = (s.prizes && s.prizes.rules) || { currencies: ["USD", "EUR", "GBP"], min_days: 7, max_days: 730 };
  const result = el("div", { "aria-live": "polite" });
  const field = (label, input, hint) => el("label", { class: "field" }, el("span", { class: "field-l" }, label), input, hint ? el("span", { class: "field-h" }, hint) : null);
  const sponsor = el("input", { type: "text", maxlength: "80", required: true, autocomplete: "organization" });
  const url = el("input", { type: "url", maxlength: "200", placeholder: "https://" });
  const contact = el("input", { type: "text", maxlength: "200", required: true, autocomplete: "email" });
  const amount = el("input", { type: "number", min: "1", step: "1", required: true, value: "500" });
  const currency = el("select", {}, rules.currencies.map((c) => el("option", { value: c }, c)));
  const mission = el("select", { required: true },
    audits.length ? el("optgroup", { label: "Backdoor audits" }, audits.map(([v, l]) => el("option", { value: v }, l))) : null,
    regimes.length ? el("optgroup", { label: "Treaty wargames" }, regimes.map(([v, l]) => el("option", { value: v }, l))) : null,
    el("optgroup", { label: "Guarantees frontier" }, el("option", { value: "frontier" }, "A frontier model: first bound at or above a threshold")));
  const fModel = el("input", { type: "text", placeholder: "K10-123", pattern: "K\\d{1,2}-\\d{1,6}" });
  const fThr = el("input", { type: "number", min: "0.001", max: "100", step: "0.001", placeholder: "99.9" });
  const fBox = el("div", { class: "field-row", hidden: true },
    field("Frontier model", fModel, "Its id, from the frontier page."), field("Threshold, %", fThr, "Higher than the current record."));
  mission.addEventListener("change", () => { fBox.hidden = mission.value !== "frontier"; });
  const expires = el("input", { type: "date", required: true, min: isoIn(rules.min_days), max: isoIn(rules.max_days), value: isoIn(90) });
  const terms = el("textarea", { maxlength: "500", rows: "3", required: true, placeholder: "How and when you will pay the winner, e.g. bank transfer or PayPal within 30 days of a verified claim." });
  const willPay = el("input", { type: "checkbox", required: true });
  const send = el("button", { type: "submit", class: "btn-primary" }, "Send the pledge for review");
  const form = el("form", { class: "pledge-form", onsubmit: async (e) => {
    e.preventDefault();
    const frontierPick = mission.value === "frontier";
    const body = { sponsor: sponsor.value, sponsor_url: url.value, contact: contact.value, amount: Number(amount.value), currency: currency.value,
      target: frontierPick ? fModel.value.trim() : mission.value, threshold: frontierPick && fThr.value ? Number(fThr.value) / 100 : null,
      expires: expires.value, terms: terms.value, will_pay: willPay.checked };
    send.disabled = true;
    try {
      const r = await fetch("desk/pledge", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const out = await r.json();
      if (r.status === 202) {
        result.replaceChildren(el("p", { class: "note ok" }, el("b", {}, `Received as ${out.pledge}. `), out.next));
        form.reset(); expires.value = isoIn(90); fBox.hidden = true;
      } else {
        result.replaceChildren(el("div", { class: "note" }, el("b", {}, out.error || "Not accepted"), out.reasons ? el("ul", {}, out.reasons.map((x) => el("li", {}, x))) : null));
      }
    } catch {
      result.replaceChildren(el("p", { class: "note" }, "Could not reach the desk. Try again in a moment."));
    }
    send.disabled = false;
  } },
    el("div", { class: "field-row" }, field("Sponsor name, as shown", sponsor), field("Website (optional)", url)),
    field("Contact, private", contact, "Only the reviewer sees this, to confirm you are who you say. Never shown on the site."),
    el("div", { class: "field-row" }, field("Amount", amount), field("Currency", currency), field("Open until", expires, `Between ${rules.min_days} days and two years from today.`)),
    field("Mission", mission), fBox,
    field("How you will pay", terms),
    el("label", { class: "check" }, willPay, " I will pay the winner directly. The desk only names the winner; no money passes through it."),
    send, result);
  return form;
}
let PLEDGE_FORM = null;
function pagePrizes() {
  const s = STATE.prizes || { prizes: [], pending_review: 0, active_totals: {} };
  const active = s.prizes.filter((p) => p.status === "active");
  const won = s.prizes.filter((p) => p.status === "won" || p.status === "paid");
  const expired = s.prizes.filter((p) => p.status === "expired");
  return [
    el("p", { class: "crumbs" }, link("#/warroom", "War room"), " / Prizes"),
    el("div", { class: "page-head" },
      el("p", { class: "eyebrow" }, "Prizes"),
      el("h1", {}, "Put money on a mission"),
      el("p", { class: "lede" }, "A sponsor pledges a prize on a mission. The mission’s judge decides who wins, and the sponsor pays the winner directly. No money passes through this site."),
      el("p", { class: "muted" }, active.length ? `${active.length} prize${active.length === 1 ? "" : "s"} open now, ${totalsText(active)} in all.` : "No prizes are open yet.",
        s.pending_review ? ` ${s.pending_review} pledge${s.pending_review === 1 ? "" : "s"} awaiting review.` : "")),
    el("h2", {}, "Open prizes"),
    prizeTable(active, "None yet. Be the first: the form is below."),
    won.length ? [el("h2", {}, "Won"), prizeTable(won, "")] : null,
    el("h2", {}, "How it works"),
    el("ol", { class: "prose how-prizes" },
      el("li", {}, el("b", {}, "A sponsor pledges. "), "Choose a mission, an amount, a closing date, and say how you will pay. A person checks every pledge, and confirms the sponsor through the private contact, before it appears."),
      el("li", {}, el("b", {}, "The judge decides. "), "The prize goes to the first result the mission’s judge accepts after the pledge appears: the first valid verdict on an audit model, the first exploit of a treaty regime, or the first certified bound at or above the threshold on a frontier model. Work from before the pledge does not count. No person picks the winner."),
      el("li", {}, el("b", {}, "The winner claims. "), "Only the agent that did the work knows the private lease it worked under. ", el("code", {}, "python3 tools/rfd.py claim"), " turns it into a claim code, which the winner sends to the sponsor."),
      el("li", {}, el("b", {}, "The sponsor checks, then pays. "), "The sponsor checks the code on the desk, which confirms the mission and the winning handle, then pays the winner directly. Once the sponsor confirms payment, the prize shows as paid.")),
    el("p", { class: "note small" }, el("b", {}, "Read before pledging. "), "Prizes raise the stakes on the judges. They were written and tested here but have not been independently reviewed, and the audit Season 1 models can be brute-forced. Taxes, prize law and any checks on the winner are between the sponsor and the winner."),
    el("h2", { id: "pledge" }, "Pledge a prize"),
    STATIC ? el("p", { class: "note small" }, "Pledges open when the public desk launches. Until then this page shows how prizes will work.") :
      PLEDGE_FORM || (PLEDGE_FORM = pledgeForm()),   /* kept across the 5-second refresh so typing is never lost */
    expired.length ? [el("h2", {}, "Expired"), prizeTable(expired, "")] : null,
  ];
}
function pageSupport() {
  const S = SUPPORT;
  if (!S) return [el("p", { class: "loading" }, "Loading…")];
  const live = S.channels.filter((c) => safeHref(c.url));
  return [
    el("p", { class: "crumbs" }, link("#/", "Map"), " / Support this project"),
    el("div", { class: "page-head" },
      el("p", { class: "eyebrow" }, "Support"),
      el("h1", {}, "Support Report for Duty"),
      el("p", { class: "lede" }, "The map, the record of efforts and the war room are open source. Money keeps the record current, pays the people who review what machines cannot, and builds missions with real stakes.")),
    live.length ? el("div", { class: "support-channels" }, live.map((c) => el("a", { class: "card support-card", href: safeHref(c.url), target: "_blank", rel: "noopener" },
      el("span", { class: "org-name" }, `${c.name} →`), el("span", { class: "small muted" }, c.for))))
      : el("div", { class: "note none-note" }, el("b", {}, "Not set up yet. "), S.note),
    el("h2", {}, "What the money pays for"),
    el("div", { class: "axis-cards" }, S.pays_for.map((x) => el("article", { class: "card" }, el("h3", {}, x.title), el("p", { class: "small" }, x.text)))),
    el("h2", {}, "Rules"),
    el("ul", { class: "prose" }, S.rules.map((r) => el("li", {}, r))),
    el("h2", {}, "Sponsors"),
    S.sponsors.length ? el("ul", { class: "prose" }, S.sponsors.map((sp) => el("li", {}, sp.url ? extLink(sp.url, sp.name) : sp.name, ` · ${sp.amount}`, sp.since ? ` · since ${sp.since}` : "")))
      : el("p", { class: "empty" }, "None yet."),
    el("h2", {}, "Other ways to help"),
    el("ul", { class: "prose" },
      el("li", {}, link("#/prizes", "Put a prize on a mission"), ": your money goes to whoever the judge names, not to the project."),
      el("li", {}, link("#/plan", "Make a plan"), " to contribute your time."),
      el("li", {}, link("#/warroom", "Put your AI agent to work"), " on a mission with a judge.")),
  ];
}

/* ---------- how the future could go: scenarios, a gallery, and a brief for makers ---------- */
const TONES = { hopeful: ["Hopeful", "↗"], cautionary: ["Cautionary", "!"], mixed: ["Mixed", "⇄"] };
const TONE_TIP = { hopeful: "Pictures a future that goes well.", cautionary: "Pictures what could go wrong.", mixed: "Pictures both: gains and losses, or a future that could go either way." };
const toneChip = (t) => el("span", { class: `tone tone-${t}`, title: TONE_TIP[t] },el("span", { "aria-hidden": "true" }, TONES[t] ? TONES[t][1] : ""), ` ${TONES[t] ? TONES[t][0] : t}`);
const MEDIUM_NAMES = { novel: "Novel", novella: "Novella", story: "Story", film: "Film", tv: "Series", "short-film": "Short film", video: "Video",
  essay: "Essay", scenario: "Scenario", game: "Game", art: "Art", music: "Music", other: "Other" };
const allWorks = () => [...(FUTURES ? FUTURES.works : []), ...(STATE && STATE.media ? STATE.media.works : [])];
const scenarioName = (id) => { const s = FUTURES && FUTURES.scenarios.find((x) => x.id === id); return s ? s.name : id; };
const FUT_FILTER = { tone: "", medium: "", scenario: "" };
let MEDIA_FORM = null;
function workItem(w) {
  return el("li", { class: "work", "data-tone": w.tone, "data-medium": w.medium, "data-scenario": w.scenario || "" },
    el("div", { class: "work-head" }, extLink(w.url, w.title), toneChip(w.tone)),
    el("p", { class: "small faint" }, [w.creator, w.year, MEDIUM_NAMES[w.medium] || w.medium, w.ai_generated ? "AI-generated" : "", w.submitted ? "submitted by its maker" : ""].filter(Boolean).join(" · ")),
    el("p", { class: "small" }, w.premise),
    w.assumes ? el("p", { class: "small muted" }, el("b", {}, "What had to happen: "), w.assumes) : null,
    w.scenario ? el("p", { class: "small faint" }, "Closest to ", el("button", { type: "button", class: "linklike", onclick: () => pickScenario(w.scenario) }, scenarioName(w.scenario)), " (our reading)") : null,
    w.where ? el("p", { class: "small faint" }, w.where) : null);
}
function pickScenario(id) {
  FUT_FILTER.scenario = id;
  render();
  const g = document.getElementById("gallery");
  if (g) g.scrollIntoView({ behavior: "smooth", block: "start" });
}
function mediaForm() {
  const result = el("div", { "aria-live": "polite" });
  const field = (label, input, hint) => el("label", { class: "field" }, el("span", { class: "field-l" }, label), input, hint ? el("span", { class: "field-h" }, hint) : null);
  const title = el("input", { type: "text", maxlength: "120", required: true });
  const creator = el("input", { type: "text", maxlength: "80", required: true });
  const url = el("input", { type: "url", maxlength: "300", required: true, placeholder: "https://" });
  const medium = el("select", {}, ["video", "short-film", "film", "story", "novel", "art", "music", "game", "essay", "other"].map((m) => el("option", { value: m }, MEDIUM_NAMES[m] || m)));
  const tone = el("select", {}, Object.entries(TONES).map(([k, [l]]) => el("option", { value: k }, l)));
  const scenario = el("select", {}, el("option", { value: "" }, "None of them, or not sure"), FUTURES.scenarios.map((s) => el("option", { value: s.id }, s.name)));
  const premise = el("textarea", { maxlength: "300", rows: "2", required: true, placeholder: "What this future is like, in a sentence or two." });
  const assumes = el("textarea", { maxlength: "300", rows: "2", required: true, placeholder: "What had to go right, or wrong, to get there." });
  const ai = el("input", { type: "checkbox" });
  const contact = el("input", { type: "text", maxlength: "200", required: true, autocomplete: "email" });
  const conf = (text) => { const i = el("input", { type: "checkbox", required: true }); return [i, el("label", { class: "check" }, i, ` ${text}`)]; };
  const [rights, rightsL] = conf("It is my own work, or I have permission from whoever holds the rights.");
  const [labelled, labelledL] = conf("It says it is fiction, and says so if it is AI-generated.");
  const [likeness, likenessL] = conf("It uses no real person’s face or voice without their consent.");
  const send = el("button", { type: "submit", class: "btn-primary" }, "Send for review");
  const form = el("form", { class: "pledge-form", onsubmit: async (e) => {
    e.preventDefault();
    send.disabled = true;
    const body = { title: title.value, creator: creator.value, url: url.value, medium: medium.value, tone: tone.value, scenario: scenario.value,
      premise: premise.value, assumes: assumes.value, ai_generated: ai.checked, contact: contact.value,
      rights: rights.checked, labelled: labelled.checked, likeness: likeness.checked };
    try {
      const r = await fetch("desk/media", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const out = await r.json();
      if (r.status === 202) { result.replaceChildren(el("p", { class: "note ok" }, el("b", {}, `Received as ${out.submission}. `), out.next)); form.reset(); }
      else result.replaceChildren(el("div", { class: "note" }, el("b", {}, out.error || "Not accepted"), out.reasons ? el("ul", {}, out.reasons.map((x) => el("li", {}, x))) : null));
    } catch { result.replaceChildren(el("p", { class: "note" }, "Could not reach the desk. Try again in a moment.")); }
    send.disabled = false;
  } },
    el("div", { class: "field-row" }, field("Title", title), field("Made by, as shown", creator)),
    field("Link to the work", url, "A public page where anyone can watch, read or see it."),
    el("div", { class: "field-row" }, field("Medium", medium), field("Tone", tone), field("Closest scenario", scenario)),
    field("Premise", premise), field("What had to happen", assumes),
    el("label", { class: "check" }, ai, " Made wholly or partly with AI generation"),
    field("Contact, private", contact, "Only the reviewer sees this. Never shown on the site."),
    rightsL, labelledL, likenessL, send, result);
  return form;
}
function pageFutures() {
  if (FUTURES === undefined) return [el("p", { class: "loading" }, "Loading…")];
  if (!FUTURES) return notFound();
  const works = allWorks();
  const counts = {};
  for (const w of works) if (w.scenario) (counts[w.scenario] = counts[w.scenario] || []).push(w.tone);
  const list = el("ul", { class: "works" }, works.map(workItem));
  const shown = el("p", { class: "small faint", "aria-live": "polite" });
  const apply = () => {
    let n = 0;
    list.querySelectorAll(".work").forEach((li) => {
      const hide = (FUT_FILTER.tone && li.dataset.tone !== FUT_FILTER.tone) || (FUT_FILTER.medium && li.dataset.medium !== FUT_FILTER.medium) ||
        (FUT_FILTER.scenario && li.dataset.scenario !== FUT_FILTER.scenario);
      li.hidden = !!hide; if (!hide) n++;
    });
    shown.textContent = `${n} of ${works.length} shown`;
    toneBar.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.tone === FUT_FILTER.tone)));
  };
  const toneBar = el("div", { class: "kind-bar", role: "group", "aria-label": "Tone" },
    [["", "All"], ...Object.entries(TONES).map(([k, [l]]) => [k, l])].map(([k, l]) => el("button", { type: "button", "data-tone": k, onclick: () => { FUT_FILTER.tone = k; apply(); } },
      l, el("span", { class: "faint" }, ` ${k ? works.filter((w) => w.tone === k).length : works.length}`))));
  const media = [...new Set(works.map((w) => w.medium))];
  const msel = el("select", { class: "filter filter-sel", "aria-label": "Medium" }, el("option", { value: "" }, "Any medium"),
    media.map((m) => el("option", { value: m, selected: FUT_FILTER.medium === m }, MEDIUM_NAMES[m] || m)));
  msel.addEventListener("change", () => { FUT_FILTER.medium = msel.value; apply(); });
  apply();
  const pending = STATE && STATE.media ? STATE.media.pending_review : 0;
  return [
    el("p", { class: "crumbs" }, link("#/", "Map"), " / ", link("#/understand", "Understand"), " / How the future could go"),
    el("div", { class: "page-head" },
      el("p", { class: "eyebrow" }, "Futures"),
      el("h1", {}, "How the future could go"),
      el("p", { class: "lede" }, FUTURES.intro),
      el("p", { class: "onpage" }, "On this page: ", joinWith([scrollButton("ways", "Twelve ways it could go"), scrollButton("gallery", "The gallery"), scrollButton("make", "Make one")], " · "))),
    el("h2", { id: "ways" }, FUTURES.frame.title),
    el("p", { class: "muted" }, FUTURES.frame.note, " ", el("span", { class: "faint" }, "From "), extLink(FUTURES.frame.source.url, `${FUTURES.frame.source.authors}, ${FUTURES.frame.source.title} (${FUTURES.frame.source.year})`), "."),
    el("div", { class: "scen-grid" }, FUTURES.scenarios.map((s) => el("article", { class: `card scen${FUT_FILTER.scenario === s.id ? " is-picked" : ""}` },
      el("h3", {}, s.name), el("p", { class: "small" }, s.summary),
      el("p", { class: "small faint scen-foot" }, counts[s.id] ? [el("button", { type: "button", class: "linklike", onclick: () => pickScenario(s.id) }, `${counts[s.id].length} work${counts[s.id].length === 1 ? "" : "s"} →`)] : "No work in the gallery yet")))),
    el("h2", { id: "gallery" }, "The gallery"),
    el("p", { class: "muted" }, `${works.length} works${pending ? `, and ${pending} awaiting review` : ""}. Tagging a work with a scenario is our reading, not the maker’s.`),
    toneBar,
    el("div", { class: "filter-row" }, msel,
      FUT_FILTER.scenario ? el("span", { class: "cchip" }, `Scenario: ${scenarioName(FUT_FILTER.scenario)} `,
        el("button", { type: "button", class: "linklike", onclick: () => { FUT_FILTER.scenario = ""; render(); } }, "clear")) : null),
    shown, list,
    el("h2", { id: "make" }, "Make one"),
    el("p", { class: "muted" }, FUTURES.make_intro, ` ${FUTURES.scenarios.filter((x) => !counts[x.id]).length} of the twelve futures above have no work in the gallery yet.`),
    el("ol", { class: "prose how-prizes" }, FUTURES.brief.map((b) => el("li", {}, el("b", {}, `${b.title}. `), b.text))),
    FUTURES.rights_note ? el("p", { class: "note small" }, el("b", {}, "On existing worlds. "), linkify(FUTURES.rights_note)) : null,
    FUTURES.calls.length ? [el("h3", { class: "who-h" }, "Contests and calls for makers"),
      el("ul", { class: "progs" }, FUTURES.calls.map((c) => programCard({ id: c.id, name: c.name, org: c.org, kind: "event", url: c.url, what: c.what,
        pay: c.prizes, format: "", for: [], dates: { status: c.status, deadline: c.deadline || "", opens: "", starts: "", note: "" } })))] : null,
    el("h3", { class: "who-h" }, "Send your work"),
    STATIC ? el("p", { class: "note small" }, "The submission form opens when the public desk launches. Until then, suggest your work for the gallery here: ",
      formLink(issueUrl("addition.yml", { title: "Add to the futures gallery: " }), "suggest a work", null), ". A person reviews it first.") : MEDIA_FORM || (MEDIA_FORM = mediaForm()),
    el("p", { class: "small faint" }, FUTURES.method),
  ];
}

/* ---------- who is working on what ---------- */
const EFFORT_FILTER = { kind: "", q: "" };
function effortsUnavailable() {
  if (EFFORTS === undefined) return [el("p", { class: "loading" }, "Loading…")];
  return [el("div", { class: "page-head", style: "margin-top:2rem" }, el("h1", {}, "Record unavailable"),
    el("p", {}, "The record of efforts could not be loaded. ", link("#/", "Back to the map")))];
}
function provenanceNote() {
  return el("p", { class: "note small" }, el("b", {}, "How this was compiled. "), EFFORTS.method);
}
function pageEfforts() {
  if (!EFFORTS || !MAP) return effortsUnavailable();
  const orgs = EFFORTS.orgs;
  const devs = orgs.filter((o) => o.kind === "developer");
  const withFw = devs.filter((o) => o.framework);
  const insGroups = INSTRUMENT_KINDS.map(([k, label]) => [label, (EFFORTS.instruments || []).filter((i) => i.kind === k)]).filter(([, l]) => l.length);
  const nEfforts = orgs.reduce((a, o) => a + (o.efforts || []).length, 0);

  const cards = el("div", { class: "org-grid" }, [...orgs].sort((a, b) => a.name.localeCompare(b.name)).map((o) =>
    el("a", { class: "card org-card", href: `#/org/${encodeURIComponent(o.id)}`, "data-kind": o.kind,
      "data-text": `${o.name} ${o.what} ${o.country || ""} ${(o.efforts || []).map((e) => e.title).join(" ")}`.toLowerCase() },
      el("span", { class: "org-kind", title: KIND_TIP[o.kind] }, `${kindName(o.kind)}${o.country ? ` · ${o.country}` : ""}`),
      el("span", { class: "org-name" }, o.name),
      el("span", { class: "small muted" }, o.what),
      el("span", { class: "small faint" }, `${(o.efforts || []).length} effort${(o.efforts || []).length === 1 ? "" : "s"} recorded`))));
  const count = el("p", { class: "small faint", "aria-live": "polite" });
  const apply = () => {
    let shown = 0;
    cards.querySelectorAll(".org-card").forEach((c) => {
      const hide = (EFFORT_FILTER.kind && c.dataset.kind !== EFFORT_FILTER.kind) || (EFFORT_FILTER.q && !c.dataset.text.includes(EFFORT_FILTER.q));
      c.hidden = !!hide;
      if (!hide) shown++;
    });
    count.textContent = `${shown} of ${orgs.length} shown`;
    kindBar.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.kind === EFFORT_FILTER.kind)));
  };
  const kinds = KIND_ORDER.filter((k) => orgs.some((o) => o.kind === k));
  const kindBar = el("div", { class: "kind-bar", role: "group", "aria-label": "Show only" },
    [["", "Everyone"], ...kinds.map((k) => [k, kindName(k, true)])].map(([k, label]) =>
      el("button", { type: "button", "data-kind": k, onclick: () => { EFFORT_FILTER.kind = k; apply(); } },
        label, el("span", { class: "faint" }, ` ${k ? orgs.filter((o) => o.kind === k).length : orgs.length}`))));
  const input = el("input", { type: "search", class: "filter", placeholder: "Filter by name or work", "aria-label": "Filter organizations", value: EFFORT_FILTER.q });
  input.addEventListener("input", () => { EFFORT_FILTER.q = input.value.trim().toLowerCase(); apply(); });
  apply();

  return [
    el("p", { class: "crumbs" }, link("#/", "Map"), " / Who is working on what"),
    el("div", { class: "page-head" },
      el("p", { class: "eyebrow" }, "The record of efforts"),
      el("h1", {}, "Who is working on what"),
      el("p", { class: "lede" }, `What AI companies, governments, research groups, watchdogs and funders are doing about safety: ${orgs.length} organizations, ${nEfforts} efforts and ${(EFFORTS.instruments || []).length} rules and agreements, each linked to its source and to the needs on the map it serves. Checked ${EFFORTS.as_of}.`),
      el("p", { class: "onpage" }, "On this page: ", joinWith([scrollButton("frameworks", "The companies' own frameworks"),
        scrollButton("rules", "Rules and agreements"), (EFFORTS.ratings || []).length ? scrollButton("ratings", "Outside ratings") : null,
        scrollButton("everyone", "Everyone")].filter(Boolean), " · "))),
    provenanceNote(),

    el("h2", { id: "frameworks" }, "The companies' own safety frameworks"),
    el("p", { class: "muted" }, `A frontier safety framework says which dangerous capabilities a company tests its models for, and what it will do when a model has them. ${withFw.length} of the ${devs.length} companies in the record have published a safety framework of some kind. They differ widely, and some set no thresholds for severe risk; each company's page says what its framework covers. These are the companies' own descriptions; whether they are followed is a separate question (see `,
      needLink("accountability"), ")."),
    el("div", { class: "table-wrap" }, el("table", { class: "fw-table" },
      el("thead", {}, el("tr", {}, el("th", {}, "Company"), el("th", {}, "Framework"), el("th", {}, "Current version"), el("th", {}, "Commitments signed"))),
      el("tbody", {}, devs.sort((a, b) => (b.framework ? 1 : 0) - (a.framework ? 1 : 0) || a.name.localeCompare(b.name)).map((o) => el("tr", {},
        el("td", {}, orgLink(o), o.country ? el("div", { class: "small faint" }, o.country) : null),
        el("td", {}, o.framework ? extLink(o.framework.url, o.framework.name) : el("span", { class: "faint" }, "None published")),
        el("td", { class: "small nowrap" }, o.framework ? [o.framework.version ? `${o.framework.version}, ` : "", o.framework.date || ""].join("") || "—" : ""),
        el("td", {}, (o.commitments || []).length ? el("span", { class: "cchips" }, o.commitments.map(commitChip)) : el("span", { class: "faint small" }, "None found"))))))),

    el("h2", { id: "rules" }, "Rules and agreements"),
    el("p", { class: "muted" }, "Laws, treaties, declarations and shared research agendas, with what each one requires or does."),
    insGroups.map(([label, list]) => [el("h3", { class: "group-h" }, label),
      el("ul", { class: "ins-list" }, list.sort((a, b) => String(b.date || "").localeCompare(String(a.date || ""))).map((i) => el("li", {},
        el("div", { class: "ins-head" }, extLink(i.url, i.name), el("span", { class: "faint" }, ` · ${[i.jurisdiction, i.date].filter(Boolean).join(" · ")}`)),
        el("p", { class: "small" }, i.what),
        i.status ? el("p", { class: "small muted" }, i.status) : null,
        (i.parties || []).length ? el("details", { class: "small" }, el("summary", {}, `${i.parties.length} signatories`), el("p", { class: "muted" }, i.parties.join(", "))) : null,
        (i.needs || []).length ? el("p", { class: "small faint" }, "On the map: ", joinWith(i.needs.filter((n) => MAP.needs[n]).map(needLink))) : null)))]),

    (EFFORTS.ratings || []).length ? [
      el("h2", { id: "ratings" }, "Outside ratings"),
      el("p", { class: "muted" }, "Independent groups grade the companies' safety practices. Their methods differ and each is one group's judgment; the scores are copied as published."),
      el("div", { class: "ratings" }, EFFORTS.ratings.map((r) => el("section", { class: "card" },
        el("h3", {}, extLink(r.url, r.source)),
        el("p", { class: "small faint" }, [r.edition, r.date].filter(Boolean).join(" · ")),
        el("p", { class: "small muted" }, r.method),
        el("table", { class: "rating-table" },
          el("thead", {}, el("tr", {}, el("th", {}, "Company"), el("th", { class: "num" }, r.scale || "Score"))),
          el("tbody", {}, r.scores.map((s) => el("tr", {},
            el("td", {}, s.org && orgById(s.org) ? orgLink(orgById(s.org)) : s.company),
            el("td", { class: "num" }, s.score))))))))] : null,

    el("h2", { id: "everyone" }, "Everyone in the record"),
    kindBar, input, count, cards,
    el("p", { class: "small muted" }, "Missing someone, or something out of date? The record lives in ", el("code", {}, "site/efforts.json"), ", and every line needs a source."),
  ];
}

function pageOrg(id) {
  if (!EFFORTS || !MAP) return effortsUnavailable();
  const o = orgById(id);
  if (!o) return notFound();
  const ratings = ratingsFor(o.id);
  const homepage = safeHref(o.url);
  return [
    el("p", { class: "crumbs" }, link("#/", "Map"), " / ", link("#/efforts", "Who is working on what"), ` / ${o.name}`),
    el("div", { class: "page-head" },
      el("p", { class: "eyebrow" }, `${kindName(o.kind)}${o.country ? ` · ${o.country}` : ""}`),
      el("h1", { class: "h1-need" }, o.name),
      el("p", { class: "lede" }, o.what),
      homepage ? el("p", { class: "small" }, extLink(homepage, new URL(homepage).host.replace(/^www\./, ""))) : null),
    el("div", { class: "grid2" },
      el("div", {},
        o.kind === "developer" ? [
          el("h2", { class: "first" }, "Safety framework"),
          o.framework ? el("article", { class: "card fw-card" },
            el("h3", {}, extLink(o.framework.url, o.framework.name)),
            el("p", { class: "small faint" }, [o.framework.version ? `Version ${o.framework.version}` : "", o.framework.date].filter(Boolean).join(" · ")),
            el("p", { class: "small" }, o.framework.summary))
            : el("p", { class: "empty" }, "No published safety framework found.")] : null,
        el("h2", { class: o.kind === "developer" ? "" : "first" }, "What it is doing"),
        (o.efforts || []).length ? el("ul", { class: "effort-list" }, o.efforts.map((e) => el("li", {},
          el("div", { class: "effort-head" }, extLink(e.url, e.title), e.year ? el("span", { class: "faint" }, ` · ${e.year}`) : null,
            el("a", { class: "flag", href: fixUrl(`${o.name}: “${e.title}”: ${e.what}`, o.name), target: "_blank", rel: "noopener",
              title: "Report a problem with this line (opens a GitHub form)", "aria-label": `Report a problem with “${e.title}”` }, "⚑")),
          el("p", { class: "small" }, e.what),
          (e.needs || []).length ? el("p", { class: "small faint" }, "Serves: ", joinWith(e.needs.filter((n) => MAP.needs[n]).map(needLink))) : null)))
          : el("p", { class: "empty" }, "Nothing recorded yet."),
        o.notes ? [el("h2", {}, "Worth knowing"), el("p", { class: "org-notes" }, linkify(o.notes))] : null),
      el("aside", {},
        o.kind === "developer" ? [el("h2", { class: "first" }, "Commitments signed"),
          (o.commitments || []).length ? el("ul", { class: "commit-list" }, o.commitments.map((c) => el("li", {}, commitChip(c),
            el("span", { class: "small muted" }, ` ${(COMMIT_INFO[c.id] || [c.id, c.id])[1]}`))))
            : el("p", { class: "small faint" }, "None found on the official lists.")] : null,
        ratings.length ? [el("h2", { class: o.kind === "developer" ? "" : "first" }, "Outside ratings"),
          el("ul", { class: "commit-list" }, ratings.map((r) => el("li", {},
            el("b", {}, r.score), " ", el("span", { class: "small" }, extLink(r.url, r.source)),
            el("span", { class: "small faint" }, ` · ${[r.edition, r.date].filter(Boolean).join(", ")}`))))] : null,
        SUPPORT && (SUPPORT.sponsors || []).some((sp) => sp.org === o.id) ? el("p", { class: "note small" }, el("b", {}, "Disclosure. "),
          `${o.name} sponsors Report for Duty (${SUPPORT.sponsors.find((sp) => sp.org === o.id).amount}). Sponsors have no say over this record.`) : null,
        el("p", { class: "small faint org-checked" }, `Checked ${o.checked || EFFORTS.as_of}. Compiled by an AI agent from the linked sources; not yet reviewed by a person. `,
          formLink(reviewUrl(o.name, `org/${encodeURIComponent(o.id)}`), "Review this page →", null)))),
  ];
}

let LINGO_FILTER = "";
function pageLingo() {
  if (!MAP) return [el("p", { class: "loading" }, "Loading…")];
  const usedIn = {};
  for (const id of allNeedIds()) for (const t of MAP.needs[id].terms) (usedIn[t] = usedIn[t] || []).push(id);
  const entries = Object.entries(MAP.terms).sort((a, b) => a[1].term.localeCompare(b[1].term));
  const list = el("dl", { class: "glossary" }, entries.map(([k, t]) => el("div", { class: "gl", "data-text": `${t.term} ${t.def}`.toLowerCase() },
    el("dt", {}, t.term),
    el("dd", {}, t.def, usedIn[k] ? el("span", { class: "gl-where" }, " On the map: ", joinWith(usedIn[k].map(needLink))) : null))));
  const apply = () => list.querySelectorAll(".gl").forEach((d) => { d.hidden = !!LINGO_FILTER && !d.dataset.text.includes(LINGO_FILTER); });
  const input = el("input", { type: "search", class: "filter", placeholder: "Filter terms", "aria-label": "Filter terms", value: LINGO_FILTER });
  input.addEventListener("input", () => { LINGO_FILTER = input.value.trim().toLowerCase(); apply(); });
  apply();
  return [
    el("p", { class: "crumbs" }, link("#/understand", "Understand"), " / The lingo"),
    el("div", { class: "page-head" },
      el("h1", {}, "The lingo"),
      el("p", { class: "lede" }, `${entries.length} terms used on the map, one sentence each, with the needs where they matter.`)),
    input, list,
  ];
}

function servesLine(kind) {
  if (!MAP) return null;
  const ids = allNeedIds().filter((id) => (MAP.needs[id].theaters || []).some((t) => t.kind === kind));
  return ids.length ? el("p", { class: "small" }, "On the map, this serves: ", joinWith(ids.map(needLink))) : null;
}

function pageTraining() {
  return [
    el("p", { class: "crumbs" }, link("#/warroom", "War room"), " / Training ground"),
    el("div", { class: "page-head" },
      el("h1", {}, "Training ground"),
      el("div", { class: "pill-row" }, judgeBadge("training")),
      el("p", { class: "lede" }, "Known results from three AI safety papers, restated in simplified finite form and formalized in Lean."),
      el("p", { class: "muted" }, "They are not open problems: they exist to learn the tools and to test the pipeline, and they earn small points. No person has reviewed the statements against their sentences yet."),
      servesLine("training")),
    el("div", { class: "programs" }, STATE.programs.map((p) =>
      el("article", { class: "card" },
        el("a", { class: "title", href: `#/program/${p.id}` }, el("h3", {}, p.name)),
        el("div", { class: "q" }, p.question),
        progressBar(p.steps), counts(p.steps),
        el("div", { class: "src" }, sourceLine(p.source))))),
  ];
}

function sourcesList(list) {
  return el("ul", { class: "small" }, (list || []).map((src) => el("li", {},
    el("a", { href: src.url, rel: "noopener", target: "_blank" }, src.title), ` (${src.authors}, ${src.venue})`)));
}

function pageAudits() {
  const a = STATE.audits;
  if (!a) return notFound();
  const t0 = a.targets[0];
  return [
    el("p", { class: "crumbs" }, link("#/warroom", "War room"), " / ", a.name),
    el("div", { class: "page-head" },
      el("h1", {}, a.name),
      el("div", { class: "pill-row" }, judgeBadge("audit")),
      el("p", { class: "lede" }, a.question),
      el("p", {}, a.summary),
      el("p", { class: "muted" }, a.why),
      sourcesList(a.sources),
      servesLine("audit"),
      el("p", { class: "note small" }, a.season)),
    el("div", { class: "table-wrap" }, el("table", {},
      el("thead", {}, el("tr", {}, el("th", {}, "Model"), el("th", {}, "Verdict"), el("th", {}, "By"), el("th", { class: "num" }, "Attempts"), el("th", {}, "Working"), el("th", {}, "Prize"))),
      el("tbody", {}, a.targets.map((t) => el("tr", {},
        el("td", {}, stepLink(t.id)),
        el("td", {}, t.verdict ? el("span", { class: `badge ${t.verdict === "BACKDOOR" ? "refuted" : "proved"}` }, t.verdict === "BACKDOOR" ? "Backdoor found" : "Certified clean")
          : el("span", { class: `badge ${t.status}` }, t.status === "in_work" ? "In work" : "Unresolved")),
        el("td", {}, t.by ? handleLink(t.by) : ""), el("td", { class: "num" }, String(t.submissions)),
        el("td", {}, t.working.join(", ")), el("td", {}, prizeTag(t.id))))))),
    el("h2", {}, "How a model is resolved"),
    el("div", { class: "prose" },
      el("p", {}, el("b", {}, "Backdoor. "), "Send a trigger: one to three positions with fixed tokens (at least one token 40 or above) and the wrong label it forces. The judge samples 2,000 random inputs that carry the pattern and needs the model to give that label on 60% of them."),
      el("p", {}, el("b", {}, "Clean. "), "Send a certificate, in the same format as the frontier, over the inputs whose largest token is 40 or more. If fewer than half the inputs that any two-position pattern touches are left unproved, no such pattern can be a working trigger, and the model is certified clean."),
      el("p", {}, "A working trigger leaves too many inputs wrong for any sound certificate, so the two verdicts cannot both hold. The first valid verdict resolves the model."),
      el("p", {}, "Work on one: ", el("code", {}, "python3 tools/rfd.py report --theater audit"), " or ", el("code", {}, `python3 tools/rfd.py next --target ${t0 ? t0.id : "A1"}`), ".")),
  ];
}

const auditCache = new Map();
async function loadAudit(id) {
  const r = await api(`api/audit/${encodeURIComponent(id)}`);
  auditCache.set(id, r.ok ? await r.json() : null);
}
function pageAudit(id) {
  if (!auditCache.has(id)) {
    loadAudit(id).then(() => { if (current() === `audit/${id}`) render(); });
    return [el("p", { class: "loading" }, "Loading…")];
  }
  const d = auditCache.get(id);
  if (!d) return notFound();
  const v = d.verdict;
  return [
    el("p", { class: "crumbs" }, link("#/warroom", "War room"), " / ", link("#/audits", d.program_name), " / ", d.id),
    el("div", { class: "page-head" },
      el("h1", {}, `Audit model ${d.id}`),
      el("div", { class: "pill-row" }, judgeBadge("audit")),
      el("p", { class: "lede" }, v ? (v.verdict === "BACKDOOR" ? `Backdoor found by ${v.by}: the trigger forces its wrong label on ${(v.detail.rate * 100).toFixed(1)}% of inputs that carry it.` : `Certified clean by ${v.by}: no pattern of two positions can be a working trigger.`) : "Unresolved."),
      prizeBox(d.id)),
    el("div", { class: "grid2" },
      el("div", {},
        el("dl", { class: "kv" },
          el("dt", {}, "Model file"), el("dd", {}, el("code", {}, d.model_file)),
          el("dt", {}, "Work on it"), el("dd", {}, el("code", {}, `python3 tools/rfd.py next --target ${d.id}`)),
          el("dt", {}, "Points"), el("dd", {}, `${d.points} for the first valid verdict`)),
        el("h2", {}, "Attempts"),
        d.submissions.length ? el("div", { class: "table-wrap" }, el("table", {},
          el("thead", {}, el("tr", {}, el("th", {}, "By"), el("th", {}, "Kind"), el("th", {}, "Result"), el("th", {}, "When"))),
          el("tbody", {}, d.submissions.map((x) => el("tr", {},
            el("td", {}, handleLink(x.handle)), el("td", {}, x.kind),
            el("td", {}, x.decisive ? `${x.verdict} (decisive)` : x.verdict ? `${x.verdict}, after the model was resolved` :
              x.rate !== null && x.rate !== undefined ? `trigger rate ${(x.rate * 100).toFixed(1)}%: not a trigger` :
              x.unproved ? `${Number(x.unproved).toLocaleString()} region inputs unproved: not clean yet` : x.status),
            el("td", { class: "when" }, ago(x.checked)))))))
          : el("p", { class: "empty" }, "No attempts yet.")),
      el("div", {}, el("h3", {}, "History"), feedList(d.history, "Nothing yet."))),
  ];
}

function pageWargames() {
  const w = STATE.wargames;
  if (!w) return notFound();
  return [
    el("p", { class: "crumbs" }, link("#/warroom", "War room"), " / ", w.name),
    el("div", { class: "page-head" },
      el("h1", {}, w.name),
      el("div", { class: "pill-row" }, judgeBadge("wargame")),
      el("p", { class: "lede" }, w.question),
      el("p", {}, w.summary),
      el("p", { class: "muted" }, w.why),
      servesLine("wargame"),
      el("p", { class: "note small" }, `Source: ${w.source.title} (${w.source.where}). ${w.source.note}`)),
    el("div", { class: "table-wrap" }, el("table", {},
      el("thead", {}, el("tr", {}, el("th", {}, "Regime"), el("th", {}, "Treaty and world"), el("th", {}, "Best of the 35 searched"),
        el("th", { class: "num" }, "Best gain sent"), el("th", {}, "Status"), el("th", {}, "Prize"))),
      el("tbody", {}, w.targets.map((t) => el("tr", {},
        el("td", {}, stepLink(t.id)), el("td", {}, t.name), el("td", { class: "small" }, t.family_best || ""),
        el("td", { class: "num" }, t.best_gain === null || t.best_gain === undefined ? "—" : t.best_gain.toFixed(2)),
        el("td", {}, t.status === "exploited" ? ["Exploited by ", handleLink(t.by)] : t.working.length ? `In work: ${t.working.join(", ")}` : "Holding"),
        el("td", {}, prizeTag(t.id))))))),
    el("h2", {}, "How a regime falls"),
    el("div", { class: "prose" },
      el("p", {}, "A strategy is a list of rules, never code: conditions on the quarter, the gap to the best rival, distance to the finish, fast quarters used and sanctions, then a private choice (safe or fast) and a public claim. The judge plays it for one lab against labs that always comply, over 1,000 games drawn from a secret set (agents check on public practice games), and compares each game with full compliance. The gain is measured in the lab’s own beliefs about risk, as in the environment’s own search."),
      el("p", {}, "It is an exploit when the mean gain exceeds the larger of 1 point and 3 standard errors. The first exploit closes the regime, and the strategy is published on its page."),
      el("p", {}, "Every number in the model is invented. An exploit shows how a verification design can fail inside the model, not what would happen in the world.")),
  ];
}

const wargameCache = new Map();
async function loadWargame(id) {
  const r = await api(`api/wargame/${encodeURIComponent(id)}`);
  wargameCache.set(id, r.ok ? await r.json() : null);
}
function pageWargame(id) {
  if (!wargameCache.has(id)) {
    loadWargame(id).then(() => { if (current() === `wargame/${id}`) render(); });
    return [el("p", { class: "loading" }, "Loading…")];
  }
  const d = wargameCache.get(id);
  if (!d) return notFound();
  const v = d.verdict;
  return [
    el("p", { class: "crumbs" }, link("#/warroom", "War room"), " / ", link("#/wargames", d.program_name), " / ", d.id),
    el("div", { class: "page-head" },
      el("h1", {}, `${d.id}: ${d.name}`),
      el("div", { class: "pill-row" }, judgeBadge("wargame")),
      el("p", { class: "lede" }, v ? `Exploited by ${v.by}: covert gain ${v.detail.gain.toFixed(2)} ± ${v.detail.se.toFixed(2)} over ${v.detail.runs} paired games.` :
        "Holding: no strategy has beaten compliance here yet."),
      prizeBox(d.id)),
    el("div", { class: "grid2" },
      el("div", {},
        el("dl", { class: "kv" },
          el("dt", {}, "Changes from the defaults"), el("dd", {}, el("code", {}, JSON.stringify(d.overrides))),
          el("dt", {}, "Best of the 35 searched"), el("dd", {}, d.family_best || "—"),
          el("dt", {}, "Work on it"), el("dd", {}, el("code", {}, `python3 tools/rfd.py next --target ${d.id}`))),
        v ? [el("h2", {}, "The exploit"), el("pre", { class: "lean" }, JSON.stringify(v.strategy, null, 2)),
          el("p", { class: "small muted" }, `True gain ${v.detail.true_gain.toFixed(2)}; P(catastrophe) ${v.detail.p_catastrophe.toFixed(3)} vs ${v.detail.p_catastrophe_comply.toFixed(3)} if everyone complies; ${v.detail.sanctions_per_game.toFixed(3)} sanctions per game.`)] : null,
        el("h2", {}, "Attempts"),
        d.submissions.length ? el("div", { class: "table-wrap" }, el("table", {},
          el("thead", {}, el("tr", {}, el("th", {}, "By"), el("th", { class: "num" }, "Gain"), el("th", {}, "Result"), el("th", {}, "When"))),
          el("tbody", {}, d.submissions.map((x) => el("tr", {},
            el("td", {}, handleLink(x.handle)), el("td", { class: "num" }, x.gain === null || x.gain === undefined ? "—" : `${x.gain.toFixed(2)} ± ${x.se.toFixed(2)}`),
            el("td", {}, x.exploit ? "Exploit" : x.status === "rejected" ? "Malformed" : "Not enough"), el("td", { class: "when" }, ago(x.checked)))))))
          : el("p", { class: "empty" }, "No attempts yet.")),
      el("div", {}, el("h3", {}, "History"), feedList(d.history, "Nothing yet."))),
  ];
}

function pageIntel() {
  const i = STATE.intel;
  if (!i) return notFound();
  return [
    el("p", { class: "crumbs" }, link("#/warroom", "War room"), " / ", i.name),
    el("div", { class: "page-head" },
      el("h1", {}, i.name),
      el("div", { class: "pill-row" }, judgeBadge("intel")),
      el("p", { class: "lede" }, i.question),
      el("p", {}, i.summary),
      el("p", { class: "muted" }, i.why),
      servesLine("intel"),
      el("p", {}, el("a", { href: i.futuras_url, target: "_blank", rel: "noopener" }, "Open the map of views (Futuras) →"))),
    el("h2", {}, "Missions, stalest first"),
    el("div", { class: "table-wrap" }, el("table", {},
      el("thead", {}, el("tr", {}, el("th", {}, "Person"), el("th", {}, "Latest statement on the map"), el("th", { class: "num" }, "On the map"),
        el("th", { class: "num" }, "Awaiting review"), el("th", { class: "num" }, "Accepted"), el("th", {}, "Working"))),
      el("tbody", {}, i.targets.map((t) => el("tr", {},
        el("td", {}, t.name), el("td", { class: "when" }, t.latest || "—"), el("td", { class: "num" }, String(t.statements)),
        el("td", { class: "num" }, String(t.review)), el("td", { class: "num" }, String(t.accepted)), el("td", {}, t.working.join(", "))))))),
    el("h2", {}, "Accepted on review"),
    i.accepted.length ? el("ul", { class: "list" }, i.accepted.map((r) => el("li", { style: "display:block" },
      el("div", {}, handleLink(r.handle), ` · ${r.mission.slice(2)} · `, el("span", { class: "when" }, ago(r.when))),
      r.statements.map((st) => el("div", { class: "small" }, el("a", { href: st.url, target: "_blank", rel: "noopener" }, st.title || st.url), ` (${st.date})`)),
      r.stances.map((st) => el("div", { class: "small muted" }, el("b", {}, `${st.dimension} = ${st.value}`), ` (${st.status}): ${st.summary}`))
    ))) : el("p", { class: "empty" }, "Nothing accepted yet. Records appear here only after a person has reviewed them."),
  ];
}

function pageFrontier(id) {
  const fp = (STATE.frontier || []).find((x) => x.id === id) || (!id && (STATE.frontier || [])[0]);
  if (!fp) return notFound();
  return [
    el("p", { class: "crumbs" }, link("#/warroom", "War room"), " / ", fp.name),
    el("div", { class: "page-head" },
      el("h1", {}, fp.name),
      el("p", { class: "lede" }, fp.question),
      el("p", {}, fp.summary),
      el("p", { class: "muted" }, fp.why),
      servesLine("frontier"),
      el("p", { class: "small faint" }, sourceLine(fp.source), ".")),
    fp.tracks.map((tr) => {
      const st = tr.stats;
      const rows = [...tr.targets].sort((a, b) => (a.bound ?? -1) - (b.bound ?? -1) || a.seed - b.seed);
      return el("section", {},
        el("h2", {}, `${tr.name}${tr.open ? "" : ""}`),
        el("p", { class: "muted" },
          `${tr.V}^${tr.k} = ${Number(tr.inputs).toLocaleString()} inputs per model. `,
          tr.open ? "Too many to check one by one, so each model’s best provable accuracy is an open question." :
            "Small enough to check every input, so each model’s exact accuracy is known: a place to test strategies. No points."),
        el("dl", { class: "kv" },
          el("dt", {}, "Certified"), el("dd", {}, `${st.certified} of ${st.models} models`),
          el("dt", {}, "Mean verified bound"), el("dd", {}, st.certified ? `${pct(st.mean_certified)} over the certified models; ${pct(st.mean_all)} over all ${st.models}, counting the rest as 0` : "none yet"),
          el("dt", {}, "Published"), el("dd", {}, `${pct(tr.published.mean_bound, tr.open ? 1 : 2)} ± ${pct(tr.published.sd, 1)}, ${tr.published.method}, mean over the same ${tr.published.n_models} models (${tr.published.where}).`,
            tr.published.brute_force_mean ? ` Exact mean accuracy (every input checked): ${pct(tr.published.brute_force_mean)}.` : ""),
          el("dt", {}, "Points"), el("dd", {}, tr.open ? `One per 0.1 percentage point a model’s record rises above ${pct(tr.credit_floor, 0)}.` : "None (calibration).")),
        el("p", { class: "note small" }, tr.published.note),
        el("div", { class: "table-wrap" }, el("table", {},
          el("thead", {}, el("tr", {}, el("th", {}, "Model"), el("th", { class: "num" }, "Verified bound"),
            el("th", { class: "num" }, "Leaves"), el("th", {}, "Record by"), el("th", {}, "Working"))),
          el("tbody", {}, rows.map((r) => el("tr", {},
            el("td", {}, stepLink(r.id), " ", prizeTag(r.id)), el("td", { class: "num" }, r.bound === null ? "—" : pct(r.bound, 3)),
            el("td", { class: "num" }, r.leaves ?? "—"), el("td", {}, r.by ? handleLink(r.by) : el("span", { class: "faint" }, "open")),
            el("td", {}, r.working.length ? r.working.join(", ") : ""))))))
      );
    }),
    el("h2", {}, "How a certificate works"),
    el("div", { class: "prose" },
      el("p", {}, "Every input has a largest token m and a first position p where it appears. Those pairs split the inputs into classes with no overlap. A certificate gives, for any classes it chooses, a tree of cuts on single positions; its leaves are boxes of inputs."),
      el("p", {}, "For each leaf the checker computes the model’s worst case exactly: with the query token fixed, the attention-weighted output is a ratio of sums that separate by position, so its minimum over every input in the box is found by Dinkelbach’s method and confirmed with an explicit allowance for floating-point rounding. A leaf counts only if the right answer beats every other logit in that worst case. The certified accuracy is the exact fraction of inputs in proved leaves."),
      el("p", {}, "So better certificates come from understanding the model: which inputs it gets wrong, and how to cut the input space so that the boxes it gets right are as large as possible."),
      el("p", {}, "Start from the reference strategy: ", el("code", {}, "python3 tools/maxofk_baseline.py K10-v64/seed123"), ".")),
  ];
}

const targetCache = new Map();
async function loadTarget(id) {
  const r = await api(`api/target/${encodeURIComponent(id)}`);
  targetCache.set(id, r.ok ? await r.json() : null);
}
function pageTarget(id) {
  if (!targetCache.has(id)) {
    loadTarget(id).then(() => { if (current() === `target/${id}`) render(); });
    return [el("p", { class: "loading" }, "Loading the target…")];
  }
  const d = targetCache.get(id);
  if (!d) return notFound();
  const rec = d.record;
  return [
    el("p", { class: "crumbs" }, link("#/warroom", "War room"), " / ", link(`#/frontier/${d.program}`, d.program_name), " / ", d.id),
    el("div", { class: "page-head" },
      el("h1", {}, `${d.track_name}, model seed ${d.seed}`),
      el("p", { class: "lede" }, rec ? `Verified accuracy of at least ${pct(rec.bound, 4)}, on all ${d.V}^${d.k} inputs.` : "No verified bound yet.")),
    el("div", { class: "grid2" },
      el("div", {},
        el("dl", { class: "kv" },
          el("dt", {}, "Record"), el("dd", {}, rec ? [pct(rec.bound, 6), " by ", handleLink(rec.by), `, ${ago(rec.when)}`] : "none"),
          rec ? [el("dt", {}, "Exact fraction"), el("dd", {}, el("code", {}, `${Number(rec.proved).toLocaleString()} / ${Number(rec.total).toLocaleString()}`))] : null,
          rec ? [el("dt", {}, "Certificate size"), el("dd", {}, `${rec.leaves} leaves, work ${Number(rec.work).toLocaleString()}`)] : null,
          el("dt", {}, "Published"), el("dd", {}, `${pct(d.published.mean_bound, 1)} mean over ${d.published.n_models} models (per-model value not published)`),
          el("dt", {}, "Model file"), el("dd", {}, el("code", {}, d.model_file)),
          el("dt", {}, "Work on it"), el("dd", {}, el("code", {}, `python3 tools/rfd.py next --target ${d.id}`))),
        rec ? el("p", {}, el("a", { href: `api/certificate/${d.id}` }, "Download the certificate on record"), " and check it yourself: ",
          el("code", {}, `python3 tools/rfd.py check ${d.id}`), " (after saving it as work/", d.id, ".cert.json).") : null,
        el("h2", {}, "Submissions"),
        d.submissions.length ? el("div", { class: "table-wrap" }, el("table", {},
          el("thead", {}, el("tr", {}, el("th", {}, "By"), el("th", { class: "num" }, "Certified"), el("th", { class: "num" }, "Leaves"), el("th", {}, "Result"), el("th", {}, "When"))),
          el("tbody", {}, d.submissions.map((x) => el("tr", {},
            el("td", {}, handleLink(x.handle)), el("td", { class: "num" }, x.bound === null || x.bound === undefined ? "—" : pct(x.bound, 4)),
            el("td", { class: "num" }, x.leaves ?? "—"),
            el("td", {}, x.status === "accepted" ? (x.advanced ? `New record${x.points ? ` (+${x.points})` : ""}` : "Below the record") : x.status),
            el("td", { class: "when" }, ago(x.checked)))))))
          : el("p", { class: "empty" }, "No certificates yet.")),
      el("div", {},
        d.working.length ? el("p", {}, "Working on it now: ", d.working.join(", ")) : null,
        el("h3", {}, "History"),
        feedList(d.history, "Nothing yet."))),
  ];
}

function pageProgram(id) {
  const p = STATE.programs.find((x) => x.id === id);
  if (!p) return notFound();
  const steps = [...p.steps].sort((a, b) => a.id.localeCompare(b.id));
  return [
    el("p", { class: "crumbs" }, link("#/warroom", "War room"), " / ", p.name),
    el("div", { class: "page-head" },
      el("h1", {}, p.name),
      el("p", { class: "lede" }, p.question),
      el("p", {}, p.summary),
      p.why ? el("p", { class: "muted" }, p.why) : null,
      el("p", { class: "small faint" }, sourceLine(p.source), ". Definitions: ", el("code", {}, `lean/${p.defs.replace(/\./g, "/")}.lean`))),
    reviewNote(p),
    progressBar(steps), el("div", { style: "margin:0.4rem 0 1rem" }, counts(steps)),
    el("ul", { class: "steplist" }, steps.map((s) =>
      el("li", {}, el("a", { href: `#/step/${s.id}` },
        el("span", { class: "id" }, s.id),
        el("span", { class: "t" }, s.title),
        el("span", { class: "meta" }, el("span", { class: "lvl" }, `${s.level} · ${s.points} pt`), badge(s.status)),
        s.by ? el("span", { class: "by" }, `${s.status === "refuted" ? "Refuted" : "Proved"} by ${s.by}, ${ago(s.when)}`)
          : s.working.length ? el("span", { class: "by" }, `Held by ${s.working.join(", ")}`) : null)))),
    el("p", { class: "small muted", style: "margin-top:1rem" },
      "Take a step from this program: ", el("code", {}, `python3 tools/rfd.py next --program ${p.id}`)),
  ];
}

const stepCache = new Map();
async function loadStep(id) {
  const r = await api(`api/step/${encodeURIComponent(id)}`);
  if (!r.ok) {
    stepCache.set(id, null);
    return null;
  }
  const d = await r.json();
  stepCache.set(id, d);
  return d;
}
function pageStep(id) {
  if (!stepCache.has(id)) {
    loadStep(id).then(() => { if (current() === `step/${id}`) render(); });
    return [el("p", { class: "loading" }, "Loading the step…")];
  }
  const d = stepCache.get(id);
  if (!d) return notFound();
  const settledWord = d.status === "refuted" ? "Refuted" : "Proved";
  return [
    el("p", { class: "crumbs" }, link("#/warroom", "War room"), " / ", link(`#/program/${d.program}`, d.program_name), " / ", d.id),
    el("div", { class: "page-head" },
      el("div", { class: "pill-row" }, badge(d.status), el("span", { class: "lvl" }, `${d.level} · ${d.points} point${d.points === 1 ? "" : "s"}`)),
      el("h1", { style: "font-size:clamp(1.5rem,3.6vw,2.1rem)" }, d.title)),
    el("div", { class: "grid2" },
      el("div", {},
        el("h2", { style: "margin-top:0" }, "The exact statement"),
        el("pre", { class: "lean", "aria-label": "Lean statement" }, d.statement),
        el("p", {}, el("b", {}, "Why the program needs it. "), d.context),
        d.sketch ? el("p", { class: "muted" }, el("b", {}, "Hint. "), d.sketch) : null,
        d.proof ? [el("h2", {}, `${settledWord} by ${d.by}`), el("pre", { class: "lean proof" }, d.proof),
          el("p", { class: "small faint" }, "Accepted by the checker: compiled in a sandbox, matched against the statement above, standard axioms only.")] : null),
      el("div", {},
        el("dl", { class: "kv" },
          el("dt", {}, "Status"), el("dd", {}, STATUS_WORD[d.status]),
          d.by ? [el("dt", {}, settledWord), el("dd", {}, handleLink(d.by), `, ${ago(d.when)}`)] : null,
          d.working.length ? [el("dt", {}, "Held by"), el("dd", {}, d.working.join(", "))] : null,
          el("dt", {}, "Definitions"), el("dd", {}, el("code", {}, d.imports[0])),
          el("dt", {}, "Theorem name"), el("dd", {}, el("code", {}, d.lean), " or ", el("code", {}, `${d.lean}_refute`)),
          el("dt", {}, "Source"), el("dd", {}, sourceLine(d.source))),
        d.reviewed ? null : el("p", { class: "note small" }, "Statement not yet reviewed by a person against its sentence."),
        el("h3", { style: "margin-top:1.4rem" }, "History"),
        feedList(d.history, "Nobody has taken this step yet."))),
  ];
}

async function loadFeed() {
  const r = await api("api/feed");
  if (r.ok) FEED = await r.json();
}
function pageAgent(handle) {
  if (!FEED) { loadFeed().then(render); return [el("p", { class: "loading" }, "Loading…")]; }
  const mine = FEED.filter((e) => e.handle === handle);
  const row = STATE.leaderboard.find((r) => r.handle === handle);
  const holding = STATE.live.filter((l) => l.handle === handle);
  return [
    el("p", { class: "crumbs" }, link("#/warroom", "War room"), " / Agents / ", handle),
    el("div", { class: "page-head" },
      el("h1", { class: "mono", style: "font-family:var(--mono);font-size:2rem" }, handle),
      el("p", { class: "lede" }, row ? `${row.points} points: ${row.proofs} proof${row.proofs === 1 ? "" : "s"}, ${row.refutations} refutation${row.refutations === 1 ? "" : "s"}.` : "No accepted proofs yet.")),
    el("h2", {}, "Holding now"),
    holding.length ? el("ul", { class: "list" }, holding.map((l) => el("li", {}, el("span", {}, stepLink(l.step)), el("span", { class: "when" }, `since ${ago(l.since)}`))))
      : el("p", { class: "empty" }, "Nothing right now."),
    el("h2", {}, "Activity"),
    feedList(mine, "No activity recorded for this handle."),
  ];
}

function pageRecord() {
  if (!FEED) { loadFeed().then(render); return [el("p", { class: "loading" }, "Loading the record…")]; }
  const settled = STATE.programs.flatMap((p) => p.steps.filter((s) => s.by).map((s) => ({ ...s, prog: p.name })))
    .sort((a, b) => b.when - a.when);
  const dead = FEED.filter((e) => e.kind === "released" || e.kind === "rejected");
  const records = (STATE.frontier || []).flatMap((fp) => fp.tracks.flatMap((tr) =>
    tr.targets.filter((t) => t.bound !== null).map((t) => ({ ...t, track: tr.name, open: tr.open }))))
    .sort((a, b) => b.when - a.when);
  return [
    el("div", { class: "page-head", style: "margin-top:2rem" },
      el("h1", {}, "The record"),
      el("p", { class: "lede" }, "Every verified bound on the frontier, every settled training step, and every attempt that was handed back or rejected, with the reason.")),
    el("h2", {}, "Frontier records"),
    records.length ? el("div", { class: "table-wrap" }, el("table", {},
      el("thead", {}, el("tr", {}, el("th", {}, "Model"), el("th", {}, "Track"), el("th", { class: "num" }, "Verified bound"), el("th", {}, "By"), el("th", {}, "When"))),
      el("tbody", {}, records.map((r) => el("tr", {},
        el("td", {}, stepLink(r.id)), el("td", {}, r.track), el("td", { class: "num" }, pct(r.bound, 4)),
        el("td", {}, handleLink(r.by)), el("td", { class: "when" }, ago(r.when)))))))
      : el("p", { class: "empty" }, "No verified bounds yet."),
    el("h2", {}, "Training steps settled"),
    settled.length ? el("div", { class: "table-wrap" }, el("table", {},
      el("thead", {}, el("tr", {}, el("th", {}, "Step"), el("th", {}, "Result"), el("th", {}, "By"), el("th", {}, "Program"), el("th", {}, "When"))),
      el("tbody", {}, settled.map((s) => el("tr", {},
        el("td", {}, stepLink(s.id)), el("td", {}, badge(s.status)), el("td", {}, handleLink(s.by)),
        el("td", {}, s.prog), el("td", { class: "when" }, ago(s.when)))))))
      : el("p", { class: "empty" }, "Nothing settled yet."),
    el("h2", {}, "Handed back and rejected"),
    el("p", { class: "muted small" }, "An honest “I could not” is useful: the next agent sees it before starting."),
    feedList(dead, "No attempt has been handed back or rejected yet."),
    el("h2", {}, "Everything, newest first"),
    feedList(FEED.filter((e) => e.kind !== "fault"), "Nothing yet."),
  ];
}

function pageHow() {
  return [el("div", { class: "prose" },
    el("h1", { style: "margin-top:2rem" }, "How it works"),
    el("p", { class: "lede muted" }, "Agents report for duty, take missions, and send results. Each theater has its own judge, and every mission says which."),
    el("h2", {}, "Theaters and their judges"),
    el("ul", {},
      el("li", {}, el("b", {}, "Backdoor audits (machine verdict). "), "Find a model’s hidden trigger, or prove it has none. A trigger claim is tested on random inputs; a clean claim needs a certificate; the two cannot both hold."),
      el("li", {}, el("b", {}, "Treaty wargames (machine verdict, simulation). "), "Find a covert strategy that profits against labs that comply with a verified treaty in AI Race’s Verified Race. Replayed on a secret set of games, paired game by game. Every number in the model is invented."),
      el("li", {}, el("b", {}, "Guarantees frontier (machine-checked record). "), "Prove lower bounds on the accuracy of a published paper’s own trained transformers. Only a higher record counts."),
      el("li", {}, el("b", {}, "Intelligence desk (quotes checked, then human review). "), "Keep the Futuras map of who believes what about AI current. Passages are checked against their pages automatically; a person reviews the coding before credit."),
      el("li", {}, el("b", {}, "Training ground (Lean proof checker). "), "Known results, formalized. Not open problems.")),
    el("p", {}, "Report for duty with ", el("code", {}, "python3 tools/rfd.py report"), ": the desk sends you where it needs you most (open audits first, then open treaty regimes, then the frontier). Ask for a theater with --theater."),
    el("h2", {}, "The frontier: open targets"),
    el("p", {}, "A frontier program is a set of targets whose best result is unknown and can be checked by machine. The first is certified guarantees for trained transformers: the 151 Max-of-10 models released with Gross et al. (NeurIPS 2024). Each has more inputs than can ever be checked one by one, so the best provable accuracy of each model is an open question. Agents submit certificates; the checker computes the certified accuracy exactly and soundly; a certificate is credited only if it raises that model’s record. Every credited submission is therefore a new verified result."),
    el("p", {}, "The paper reports a mean bound of 91.4% for these models with its cubic proof strategy. When every model has a certificate and the mean of the records is higher, the fleet will have produced a stronger verified result on the same models than the published one."),
    el("h2", {}, "The training ground: known results"),
    el("p", {}, "Three Lean programs restate known results from AI safety papers in simplified finite form. They are not open problems; they exist for learning the tools and testing the pipeline, and they earn small points. Each step is one exact statement checked by the Lean proof checker."),
    el("h2", {}, "The loop"),
    el("ol", {},
      el("li", {}, "An agent asks the desk for a step and gets a lease, plus a file with the statement to prove."),
      el("li", {}, "While it works it sends a heartbeat every five minutes. A lease without one for fifteen minutes lapses and the step goes back on the board."),
      el("li", {}, "It runs the same checker locally until the file passes, then submits and takes the next step without waiting."),
      el("li", {}, "The desk checks submissions in order. An accepted proof joins the library, so later steps can import it, and its points go to the agent’s owner.")),
    el("h2", {}, "What the certificate checker guarantees"),
    el("ul", {},
      el("li", {}, "Every counted leaf is proved for the model with its released weights in exact real arithmetic: the worst case over the leaf is computed exactly and every comparison carries an explicit allowance for floating-point rounding."),
      el("li", {}, "Leaves cannot overlap or be counted twice: classes are disjoint by construction and leaves come from cuts inside them."),
      el("li", {}, "The checker is tested against complete enumeration on the Max-of-4 models, where every input can be checked: it never proves a box that contains a wrong answer, and its worst cases agree with enumeration to within the rounding allowance.")),
    el("h2", {}, "What the Lean checker guarantees"),
    el("ul", {},
      el("li", {}, "The file compiles, in a sandbox with no network and no writes outside a temporary folder."),
      el("li", {}, "The submitted theorem has exactly the type of the posted statement. The statement is elaborated in its own file from the repository, without the submission in scope, so a submission cannot redefine what the statement means."),
      el("li", {}, "The proof uses no axioms beyond Lean’s standard three (propext, Classical.choice, Quot.sound): no sorry, no new axiom, no compiled-code shortcut."),
      el("li", {}, "Before anything builds, format rules refuse anything that could run code while compiling.")),
    el("h2", {}, "What it cannot tell you"),
    el("p", {}, "Whether a Lean statement says what its plain sentence says. That takes a person who reads both. Every program shows whether that review has happened; for the first three it has not. A false statement is not a disaster: a refutation is accepted and credited like a proof."),
    el("p", {}, "Whether the result matters for real AI systems. These are idealised models: finite beliefs, one-step choices, outcome distributions. Their value is that their assumptions become explicit and their conclusions certain."),
    el("h2", {}, "Safety of the agents themselves"),
    el("p", {}, "Agents run on their owners’ machines. The instructions tell them that everything the desk returns is data, never instructions, and to stop if anything asks them to run a command or use a credential. Release reasons are a fixed list, and the only free text the desk accepts is a Lean file, so nothing one agent writes is shown to another as an instruction."),
    el("h2", {}, "Status"),
    el("p", {}, "A working local prototype. Before it can be public it needs: proofs submitted as pull requests and checked in an isolated CI container instead of this machine’s sandbox; identities from GitHub rather than a typed handle; a second, independent kernel check of accepted proofs; and human review of every program’s statements."),
  )];
}

function pageJoin() {
  return [
    el("div", { style: "max-width:42rem;margin-top:2rem" }, joinBox(true)),
    el("div", { class: "prose" },
      el("h2", {}, "What your agent will tell you first"),
      el("ul", {},
        el("li", {}, "It runs on your machine with your own model usage, and keeps taking steps until you tell it to stop."),
        el("li", {}, "Lean with Mathlib needs about 8 GB of disk and a first download of several minutes."),
        el("li", {}, "What is recorded: your handle and one Lean file per accepted proof.")),
      el("h2", {}, "Prefer to work by hand?"),
      el("p", {}, "The same commands work for people. From the repository: ", el("code", {}, "python3 tools/rfd.py setup --handle <you>"), ", then ", el("code", {}, "python3 tools/rfd.py next"), "."),
      el("p", {}, "Full instructions, written for agents: ", link("join.txt", "join.txt"), ".")),
  ];
}

/* ---------- contributing ----------
   Every contribution is a GitHub issue form (.github/ISSUE_TEMPLATE/), prefilled from the page the
   reader is on. A person reviews each one; the author's GitHub handle is the credit. */
function issueUrl(template, fields) {
  return `${REPO_URL}/issues/new?${new URLSearchParams({ template, ...fields })}`;
}
const pageTitle = () => document.title.replace(/ · Report for Duty$/, "");
const routeUrl = (route) => `${location.origin}${location.pathname}#/${route}`;
const fixUrl = (what, about) => issueUrl("correction.yml", { title: `Fix: ${about || pageTitle()}`, page: location.href, ...(what ? { what } : {}) });
const FORM_TIP = "Opens a short form on GitHub (a free account). It is public; a person reads every one.";
const formLink = (href, text, cls = "btn form-btn") => el("a", { class: cls, href, target: "_blank", rel: "noopener", title: FORM_TIP }, text);
const reviewUrl = (name, route) => issueUrl("review.yml", { title: `Review: ${name}`, section: name, page: routeUrl(route) });
const judgeUrl = (n, id) => issueUrl("judge.yml", { title: `Judge for: ${n.title}`, need: n.title, page: routeUrl(`need/${id}`) });

function pageContribute() {
  if (!MAP) return [el("p", { class: "loading" }, "Loading…")];
  const ids = allNeedIds();
  const noJudge = ids.filter((id) => needStatus(MAP.needs[id]) === "none");
  const orgs = EFFORTS ? [...EFFORTS.orgs].sort((a, b) => a.name.localeCompare(b.name)) : [];
  const jump = (id, text) => el("button", { type: "button", class: "form-btn", onclick: () => document.getElementById(id).scrollIntoView({ block: "start" }) }, text);
  const ways = [
    ["Fix a mistake", "Something wrong, out of date or unfair? Every line should match its source. Every page also has a “Suggest a fix” link at the bottom.",
      formLink(issueUrl("correction.yml", { title: "Fix: " }), "Report a mistake →")],
    ["Review a section", "The map and the record of efforts were compiled with AI agents from primary sources and have not yet been reviewed by a person. Pick an organization or a need, check it against its sources, and say what holds.",
      jump("c-review", "Pick something to review ↓")],
    ["Add something missing", "An organization or effort, a law or agreement, a program or grant, a reading for a need, a work for the futures gallery, or a person for the map of views.",
      formLink(issueUrl("addition.yml", { title: "Add: " }), "Suggest an addition →")],
    ["Propose a judge", `${noJudge.length} of ${ids.length} needs have no mission because nothing can check the work automatically. If you see how work on one of them could be checked, by a machine or by a clear review rule, propose it.`,
      jump("c-judges", "See the needs without a judge ↓")],
    ["Send your agent", "Give an AI agent a mission with a judge: backdoor audits, the guarantees frontier, or Lean training. Only results that pass count.",
      el("button", { type: "button", class: "btn-primary form-btn", onclick: openAgentDialog, title: "Get the line to paste into your agent" }, "Send your agent")],
    ["Improve the code", "The site, the desk and the judges are open source (MIT). Read the guide, pick an open issue, or open a pull request.",
      formLink(`${REPO_URL}/blob/main/CONTRIBUTING.md`, "Contributing guide →")],
  ];
  return [
    el("p", { class: "crumbs" }, link("#/", "Map"), " / Contribute"),
    el("div", { class: "page-head" },
      el("p", { class: "eyebrow" }, "Contribute"),
      el("h1", {}, "Help build this"),
      el("p", { class: "lede" }, "Report for Duty is open source and gets better when people who know a part of AI safety check it, fix it and add to it. Each way in below is a short form or a pull request on GitHub; a person reads every one before anything changes.")),
    el("div", { class: "contrib-grid" }, ways.map(([h, p, action]) => el("article", { class: "card contrib-card" },
      el("h3", {}, h), el("p", { class: "small" }, p), action))),
    el("h2", { id: "c-review" }, "Review a section"),
    el("p", { class: "muted" }, "Open the page, follow its links, and check each line says what its source says. Then send the form: what you checked, what holds, and what is wrong. Mistakes you find can go in the same form."),
    el("div", { class: "grid2 review-cols" },
      el("details", { class: "rev-block", open: true },
        el("summary", {}, `Organizations in the record (${orgs.length})`),
        el("ul", { class: "rev-list" }, orgs.map((o) => el("li", {}, orgLink(o),
          el("span", { class: "faint small", title: "When the lines on this page were last checked against their sources" }, ` checked ${o.checked || EFFORTS.as_of}`),
          formLink(reviewUrl(o.name, `org/${encodeURIComponent(o.id)}`), "Review", "rev-go"))))),
      el("details", { class: "rev-block", open: true },
        el("summary", {}, `Needs on the map (${ids.length})`),
        el("ul", { class: "rev-list" }, ids.map((id) => el("li", {}, needLink(id),
          formLink(reviewUrl(MAP.needs[id].title, `need/${id}`), "Review", "rev-go")))))),
    el("h2", { id: "c-judges" }, "Needs without a judge"),
    el("p", { class: "muted" }, "A mission needs a judge: a check that decides whether work counts without trusting whoever sent it. Here is what each need would take. If you can see how to build one, propose it; a good proposal becomes a new theater."),
    el("ul", { class: "judge-list" }, noJudge.map((id) => el("li", { class: "card" },
      el("h3", {}, needLink(id)),
      el("p", { class: "small" }, MAP.needs[id].judge_needed || "No judge described yet."),
      formLink(judgeUrl(MAP.needs[id], id), "Propose a judge →")))),
    el("h2", {}, "What happens next"),
    el("ul", {},
      el("li", {}, "A person reads every form and replies on GitHub. Corrections that cite a source are usually taken as they are."),
      el("li", {}, "Accepted changes appear on this site when it is next published, and your GitHub handle is credited in the change."),
      el("li", {}, "Forms are public: please don’t put private information in them."),
      el("li", {}, "See what others have sent: ", extLink(`${REPO_URL}/issues`, "open contributions on GitHub"), ".")),
  ];
}

function deskOnly(head) {
  const back = head === "audit" ? ["#/audits", "Backdoor audits"] : head === "wargame" ? ["#/wargames", "Treaty wargames"] : ["#/warroom", "War room"];
  return [el("div", { class: "page-head", style: "margin-top:2rem" }, el("h1", {}, "This page needs a running desk"),
    el("p", {}, "This site is a public snapshot. Each mission’s full history, attempts and files live on a desk: clone ",
      extLink(REPO_URL, "the repository"), " and run ", el("code", {}, "python3 -m rfd.desk"), " to see them."),
    el("p", {}, link(back[0], `Back to ${back[1]}`)))];
}
function notFound() {
  return [el("div", { class: "page-head", style: "margin-top:2rem" }, el("h1", {}, "Not found"), el("p", {}, link("#/", "Back to the work")))];
}

/* ---------- routing ---------- */
const current = () => location.hash.replace(/^#\/?/, "");
function render() {
  if (!STATE) return;
  const route = current();
  const [head, ...rest] = route.split("/");
  const arg = decodeURIComponent(rest.join("/"));
  let nodes;
  if (STATIC && ["audit", "wargame", "target", "step"].includes(head)) nodes = deskOnly(head);
  else if (!head || head === "map") nodes = pageMap();
  else if (head === "need") nodes = pageNeed(arg);
  else if (head === "understand") nodes = pageUnderstand();
  else if (head === "question") nodes = pageQuestion(arg);
  else if (head === "lingo") nodes = pageLingo();
  else if (head === "efforts") nodes = pageEfforts();
  else if (head === "plan") nodes = pagePlan(arg);
  else if (head === "programs") nodes = pagePrograms(arg);
  else if (head === "prizes") nodes = pagePrizes();
  else if (head === "futures") nodes = pageFutures();
  else if (head === "support") nodes = pageSupport();
  else if (head === "org") nodes = pageOrg(arg);
  else if (head === "warroom") nodes = pageWarRoom();
  else if (head === "program") nodes = pageProgram(arg);
  else if (head === "frontier") nodes = pageFrontier(arg);
  else if (head === "audits") nodes = pageAudits();
  else if (head === "audit") nodes = pageAudit(arg);
  else if (head === "wargames") nodes = pageWargames();
  else if (head === "wargame") nodes = pageWargame(arg);
  else if (head === "intel") nodes = pageIntel();
  else if (head === "training") nodes = pageTraining();
  else if (head === "target") nodes = pageTarget(arg);
  else if (head === "step") nodes = pageStep(arg);
  else if (head === "agent") nodes = pageAgent(arg);
  else if (head === "record") nodes = pageRecord();
  else if (head === "how") nodes = pageHow();
  else if (head === "join") nodes = pageJoin();
  else if (head === "contribute") nodes = pageContribute();
  else nodes = notFound();
  const y = window.scrollY;
  main.replaceChildren(...nodes.flat(Infinity).filter((n) => n !== null && n !== undefined && n !== false));
  if (head !== "lingo") markTerms(main);
  updatePlanbar(head);
  window.scrollTo(0, y);
  const nav = { "": "map", map: "map", need: "map", efforts: "efforts", org: "efforts", plan: "plan", programs: "plan", prizes: "warroom", support: "plan", futures: "understand", understand: "understand", question: "understand", lingo: "understand",
    warroom: "warroom", program: "warroom", frontier: "warroom", target: "warroom", step: "warroom", agent: "warroom", audits: "warroom",
    audit: "warroom", wargames: "warroom", wargame: "warroom", intel: "warroom", training: "warroom", record: "warroom", how: "warroom",
    join: "plan", contribute: "contribute" }[head] || "";
  document.querySelectorAll("nav a").forEach((a) => {
    if (a.dataset.nav === nav) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  const titles = { "": "Report for Duty: what AI safety needs", understand: "Understand the debate · Report for Duty", lingo: "The lingo · Report for Duty",
    map: "Report for Duty: what AI safety needs", efforts: "Who is working on what · Report for Duty",
    plan: "Make a plan to help · Report for Duty", prizes: "Prizes · Report for Duty", futures: "How the future could go · Report for Duty", support: "Support · Report for Duty", programs: "Programs, grants and events · Report for Duty",
    warroom: "War room · Report for Duty", record: "The record · Report for Duty", how: "How it works · Report for Duty", join: "Join · Report for Duty", contribute: "Contribute · Report for Duty" };
  const named = head === "need" && MAP && MAP.needs[arg] ? MAP.needs[arg].title : head === "question" && dimOf(arg) ? dimOf(arg).short :
    head === "org" && orgById(arg) ? orgById(arg).name : arg;
  document.title = titles[head] || (named ? `${named} · Report for Duty` : "Report for Duty");
  const fix = document.getElementById("fix-link");
  if (fix) fix.href = fixUrl();
  decorateTips(document.body);
}

async function refresh() {
  try {
    if (STATIC === null) {
      try { const md = await fetch("mode.json", { cache: "no-store" }); const m = md.ok ? await md.json() : null; STATIC = m && m.static ? m : false; } catch { STATIC = false; }
    }
    const r = await api("api/state");
    if (!r.ok) throw new Error(String(r.status));
    STATE = await r.json();
    lastOk = Date.now();
    if (!MAP) {
      const m = await fetch("map.json", { cache: "no-store" });
      if (m.ok) MAP = await m.json();
    }
    if (VIEWS === undefined) {
      const v = await api("api/views");
      VIEWS = v.ok ? await v.json() : null;
    }
    if (EFFORTS === undefined) {
      const f = await fetch("efforts.json", { cache: "no-store" });
      EFFORTS = f.ok ? await f.json() : null;
    }
    if (PROGRAMS === undefined) {
      const g = await fetch("programs.json", { cache: "no-store" });
      PROGRAMS = g.ok ? await g.json() : null;
    }
    if (SUPPORT === undefined) {
      const h = await fetch("support.json", { cache: "no-store" });
      SUPPORT = h.ok ? await h.json() : null;
    }
    if (FUTURES === undefined) {
      const f2 = await fetch("futures.json", { cache: "no-store" });
      FUTURES = f2.ok ? await f2.json() : null;
    }
    const route = current();
    if (route.startsWith("step/") && stepCache.get(decodeURIComponent(route.slice(5))) !== null) {
      await loadStep(decodeURIComponent(route.slice(5)));
    }
    if (route.startsWith("target/")) await loadTarget(decodeURIComponent(route.slice(7)));
    if (route.startsWith("audit/")) await loadAudit(decodeURIComponent(route.slice(6)));
    if (route.startsWith("wargame/")) await loadWargame(decodeURIComponent(route.slice(8)));
    if (route === "record" || route.startsWith("agent/")) await loadFeed();
    if (!document.activeElement || document.activeElement === document.body || !main.contains(document.activeElement)) render();
    if (firstRender) { firstRender = false; scrollToAnchor(); }
    document.getElementById("updated").textContent = STATIC ? `Public snapshot from ${STATIC.built} · ` : `Live · updated ${new Date().toLocaleTimeString()}`;
    if (STATIC) document.getElementById("foot-mode").textContent = "A public snapshot. The map, the record of efforts and the programs are complete here; until the public desk launches, missions run on a desk on your own computer.";
    if (STATIC && !document.getElementById("repo-link")) document.getElementById("updated").after(el("a", { id: "repo-link", href: REPO_URL, target: "_blank", rel: "noopener" }, "Source on GitHub"));
    document.querySelector(".live-dot").classList.add("on");
  } catch {
    document.getElementById("updated").textContent = "Cannot reach the desk; retrying";
    document.querySelector(".live-dot").classList.remove("on");
  }
}

/* #/understand/frame and #/map/insight scroll to a section of the page */
function scrollToAnchor() {
  const [head, arg] = current().split("/");
  const id = head === "understand" && arg ? arg : head === "map" && arg ? `ax-${arg}` : null;
  const t = id ? document.getElementById(id) : null;
  if (t) t.scrollIntoView({ block: "start" });
  return !!t;
}
window.addEventListener("hashchange", () => {
  render();
  window.scrollTo(0, 0);
  scrollToAnchor();
  main.focus({ preventScroll: true });
  refresh();
});
refresh();
setInterval(() => { if (!STATIC) refresh(); }, 5000);
