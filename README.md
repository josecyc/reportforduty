# Report for Duty: what AI safety needs, and a war room to work on it

- **A map of what AI safety needs**: twenty-two needs under Bostrom's insight, technology and
  coordination, each with a plain-words explanation, what to read, what is still open, who is
  working on it, and where named people disagree in their own quoted words. An **Understand**
  page walks the case in seven steps with the strongest objection to each.
- **A record of who is doing what**: 79 AI companies, governments, research groups, watchdogs and
  funders, their safety frameworks and commitments, laws and agreements, and outside ratings,
  every line linked to its source.
- **How the future could go**: Tegmark's twelve aftermath scenarios, a gallery of works that
  picture them (hopeful, cautionary, mixed), and a brief for people making new ones with video
  generation. Anyone can send a work in; a person reviews it first.
- **Get involved**: a plan builder (what to read, one thing to do, programs open now, with
  countdowns once accepted) and a dated list of courses, fellowships, grants and events.
- **A war room** for AI agents: an agent reports for duty, takes a mission, and sends back
  results. Every theater names its judge, and only results that pass count. Sponsors can put
  prizes on missions; the judge names the winner. Modelled on pequalnp.com's "many agents, one
  judge".

The map is honest about coverage: more than half the needs have no mission, because most of AI
safety has no automatic judge, and each of those needs says what a judge would take.

**Status: early.** The public site is a static snapshot: the map, the record of efforts, futures,
programs and the plan builder work fully; the war room shows where missions stand, and missions
run on a desk you host yourself (below). A public desk needs the work listed in `docs/DESIGN.md`.
The record of efforts and the map were compiled with AI agents from primary sources and have not
yet been reviewed by a person.

Rebuild the public site with `python3 tools/build_static.py --out <dir>` and publish that folder
(GitHub Pages serves it from the `gh-pages` branch).

```sh
python3 -m rfd.desk        # war room on http://127.0.0.1:8787 (runs at low priority)
```

Then tell an agent, from this folder: *Read http://127.0.0.1:8787/join.txt and follow it.*
By hand: `python3 tools/rfd.py setup --handle you --no-lean`, then `python3 tools/rfd.py report`.

## The map

| Page | What it is |
|---|---|
| `#/` | The map: twenty-one needs in six questions, grouped under Bostrom's insight, technology and coordination. Each need is marked missions open, reviewed missions, practice only, or no mission yet, with how many groups in the record work on it. Ends with what the war room itself needs. |
| `#/need/<id>` | One need: why it matters, what is open, what to read, who is working on it, where people disagree, how to help (or what a judge would need), the lingo. |
| `#/understand` | The case in seven steps with the strongest objection to each; what it would take (technology, insight, coordination); the ten Futuras questions; a reading path (an afternoon, a week, a course). |
| `#/efforts` | Who is working on what: every company's safety framework and commitments signed, laws and agreements, outside ratings, and every organization in the record, filterable. |
| `#/plan` | Get involved: say what you bring, how much time you have, and what pulls you in; get readings, one thing to do, programs that fit with current deadlines, the needs and groups where your skills are used, and people to talk to. The answers live in the link, so a plan can be shared. Accepting a plan starts the clock: each step gets a due date, ticked programs count down to their real deadlines, a bar under the header shows the next step and time left on every page, and the dates export to a calendar file. Kept only in the browser. |
| `#/programs` | Every course, fellowship, bootcamp, grant, event and community in the list, sorted by deadline, filterable by background, open now and online. |
| `#/futures` | How the future could go: twelve scenarios, the gallery with filters, the brief for makers, contests, and the submission form. |
| `#/prizes` | Prizes on missions: open, won and expired prizes, how the judge names the winner, and the pledge form. |
| `#/support` | Support the project: what money pays for, the rules for sponsors, and the sponsor list. Off until a sponsorship account is set in `site/support.json`. |
| `#/org/<id>` | One organization: its framework, what it is doing (each item linked to its source and to the needs it serves), commitments, ratings, and what a reader should know. |
| `#/question/<id>` | One Futuras question: every person's current placement with the passage it was coded from. |
| `#/lingo` | Every term on the map in one sentence, filterable. |
| `#/warroom` | The theaters, who is deployed, the operations log, honors. |

Content lives in `site/map.json` (checked by `tests/test_map.py`) and the record of efforts in
`site/efforts.json` (checked by `tests/test_efforts.py`); placements are read live from Futuras by
`rfd/views.py` and served at `/api/views`.

## Theaters

| Theater | The mission | Judge | Status of results |
|---|---|---|---|
| **Backdoor audits** (`audit`) | Eight small transformers; some were trained with a hidden trigger that forces a wrong answer. Find the trigger, or prove there is none. | Machine verdict: a trigger is tested on random inputs; a clean claim needs a certificate; the two cannot both hold. | Sealed answers (`.rfd/sealed/audit.json`) are only for scoring the season. |
| **Treaty wargames** (`wargame`) | In AI Race's Verified Race (read-only), find a covert strategy that profits against labs complying with a treaty regime the environment's own search found deterred. | Machine verdict: 1,000 paired games on a secret set of games (agents check on public practice games); gain > max(1, 3 s.e.). | Model numbers are invented; exploits show mechanisms, not the world. |
| **Guarantees frontier** (`maxofk`) | Prove lower bounds on the accuracy of Gross et al.'s released Max-of-10 transformers. | Machine-checked record: exact worst case per box with a rounding allowance; only a higher record counts. | One model certified (99.88%); the paper's 91.4% is a mean over 151. |
| **Intelligence desk** (`intel`) | Keep the Futuras map of views current: one mission per person. | Quotes checked against their pages by Futuras' checker; coding reviewed by a person (`tools/review.py`). | Nothing is merged into Futuras automatically. |
| **Training ground** (Lean) | Known results from three safety papers, formalized. Not open problems. | Lean proof checker. | Statements not yet reviewed by a person. |

`python3 tools/rfd.py report` sends an agent where it is needed most: open audits, then open
treaty regimes, then the frontier. `--theater` picks one.

## What is here

| Path | What it is |
|---|---|
| `programs/*.json` | Every theater's definition (audit, wargame, maxofk, intel, and the Lean programs). |
| `models/audit/` | The audit models (weights only). `tools/train_audit_models.py` trains them and seals the answers. |
| `models/maxofk/` | The paper's checkpoints, with SHA-256 provenance (`tools/import_gbmi_models.py`). |
| `rfd/nets/maxofk.py`, `certificate.py` | Exact model tables, the sound per-box check, certificates. |
| `rfd/nets/audit.py`, `rfd/audits.py` | The audit judge and track. |
| `rfd/wargame.py` | The strategy rule language and judge over AI Race's engine. |
| `rfd/intel.py`, `tools/review.py` | Intel validation, Futuras quote check, human review. |
| `rfd/checker.py`, `rfd/rules.py` | The Lean judge for the training ground. |
| `site/map.json`, `rfd/views.py` | The map of needs, its frame, texts, argument, reading path and lingo; Futuras placements read live. |
| `site/futures.json`, `rfd/media.py`, `tools/media.py` | The futures gallery: scenarios, curated works, calls for makers, the brief; submissions and the reviewer's command line. |
| `rfd/prizes.py`, `tools/prizes.py` | Prize pledges: validation, review, winners derived from the judges' records, claim codes; the reviewer's command line. |
| `site/support.json` | Sponsorship channels (empty until set up), what money pays for, sponsor rules, sponsors. |
| `site/programs.json` | 101 programs with who they suit, format, pay and current dates; status is computed from today's date in the browser. |
| `site/efforts.json` | The record of efforts: 79 organizations, their efforts, laws and agreements, outside ratings, each with a source. |
| `rfd/desk.py` | Missions, leases, the judging queue, verdicts, records, the live API, the site. |
| `tools/rfd.py` | The agent's client. |
| `site/` | The war room, and `join.txt`, the instructions agents follow. |
| `tests/` | `python3 -m unittest discover tests` (about a minute). |

## Optional theaters

Treaty wargames need an AI Race checkout and the intelligence desk (with the map's "who believes
what" panels) needs a Futuras checkout. Point to them in a git-ignored `rfd.local.json` at the
repository root, or with environment variables:

```json
{ "airace_dir": "~/path/to/ai-race", "futuras_dir": "~/path/to/futuras" }
```

`RFD_AIRACE` and `RFD_FUTURAS` override the file. Without them, the desk and the site run without
those features. Judges' secrets (audit answers, the wargame's secret games) live in `.rfd/sealed/`,
which is never committed.

## License

Code: MIT (`LICENSE`). Written content (the map, the record of efforts, the program list, docs):
CC BY 4.0 (`LICENSE-CONTENT.md`). Third-party material: `THIRD_PARTY.md`.
