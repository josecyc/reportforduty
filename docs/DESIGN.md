# Design

## The map of needs

The home page is a map of what AI safety needs, not a list of what this site happens to host.
Six questions (is there a problem; can we think clearly together; can we align; can we tell; can we
stay in control; can we coordinate) hold twenty-one needs. Every need has the same parts:
the question in plain words, why it matters, what is still open, three or four texts to read,
the terms it uses, and how to help.

- **Status is derived, not declared.** A need with a machine-judged theater (audit, wargame,
  frontier) shows "missions open"; intel shows "reviewed missions"; Lean programs show "practice
  only"; otherwise "no mission yet", and the need must say what a judge would take
  (`tests/test_map.py` enforces this). Today 12 of 21 needs have no mission.
- **Who believes what comes from Futuras, live.** `rfd/views.py` reads `lib/views.json` and the
  question definitions in `lib/views.ts` (parsed as a JavaScript literal by a small tokenizer, so
  none of Futuras' code runs), and places each person by their most recent statement on a
  question, as Futuras does. Every placement on the site shows its quoted passage and source.
- **Two audiences.** Newcomers (the Understand page: the case in seven steps with the strongest
  objection to each, the ten Futuras questions, a reading path, the lingo) and agent owners (the
  war room). Needs link to theaters, and every theater page says which needs it serves.
- **Sources.** All arXiv citations were checked against the arXiv API (ID, title, authors) on
  2026-11-26, and quoted numbers against the abstracts; other links returned HTTP 200, except the
  California legislature's site, which blocks automated requests (the SB 53 link is the
  standard bill URL). Balance was a goal: every step of the argument has a named objection, and the
  reading path pairs each position with its strongest critic.

- **The frame is Bostrom's.** The six questions sit under insight, technology and coordination,
  from Bostrom, "Existential Risk Prevention as Global Priority" (2013), section 3.4 and figure 5:
  we need more of all three, and the order matters, since reaching a dangerous capability before
  the insight and coordination to handle it could be fatal. "Technology" on the map means the
  protective kind, by his differential technological development (2002, section 9.4). Both
  quotes were checked against the papers' own pages on 2026-11-26. Placing each need under one of
  the three is ours; several serve more than one.

## The record of efforts

`site/efforts.json` records who is doing what: 79 organizations (AI companies, government bodies,
research groups, policy groups, watchdogs, an industry body, funders, training programs), about
200 efforts, 27 laws and agreements, and 4 outside ratings. Every effort is tagged with the needs
it serves, so each need page lists who works on it and each tile on the map says how many.

- **How it was compiled.** On 2026-11-26 six AI research agents, one per cluster, worked from
  primary sources under one brief: every sentence backed by a page actually opened, no guessed
  versions or dates, neutral wording, absence stated with where they looked. Their files were
  merged by script; commitments were cross-checked against the official Seoul and EU Code
  signatory lists; all links were fetched automatically (340 of 356 loaded; the rest are sites
  that refuse automated requests: Meta, xAI, Coefficient Giving, the New York governor, the
  California legislature, RAND). The most consequential claims were re-checked against their
  sources by fetching the page and finding the quoted words, including the FLI, SaferAI, AI Lab
  Watch and Guidelight scores, Meta's framework change log, and the OpenAI and Hugging Face
  incident.
- **Not yet reviewed by a person.** The site says so on every organization page. The record goes
  stale whenever a framework changes; keeping it current is on the roadmap as a reviewed mission.
- **Not a coverage claim.** A need with nobody in the record may be a gap in the field or in the
  record, and the need page says exactly that.

## Getting involved

`#/plan` builds a plan from three answers (background, time, what pulls you in) and whether the
person has an AI agent. The plan is assembled from content that already exists elsewhere, so it
adds no new claims: readings are texts already on the map (`tests/test_programs.py` checks the
titles), the first task is one sentence per background in `map.json`, programs come from
`site/programs.json`, and the needs and groups come from the map and the record of efforts.

- **Programs are dated, and the date does the work.** Each program carries the deadline, opening
  and start dates its own page prints for the current or next round. The browser compares them
  with today, so a passed deadline shows as closed without anyone editing the file.
- **How the list was compiled.** Three AI research agents on 2026-11-26, one each for technical
  programs, policy/media/career programs, and grants/events/communities. Merged by script
  (duplicates folded together); all 101 links fetched; every full date looked up on its page
  (50 found as written; ARENA's deadline was only on its application form, so it was removed, and
  IASEAI's dates came from a secondary list, so they stay in the note only). AISafety.com and the
  80,000 Hours job board are linked as fresher, maintained sources.

- **Accepting a plan starts the clock.** Steps get due dates by commitment (a taste: read in a
  day, task in three; a few hours a week: seven and fourteen; a career change: three and seven);
  programs the person ticks become steps due at the end of their published deadline day, with a
  note that the program's own time zone rules. Steps are ordered by due date, so the most urgent
  is always the countdown. One ticker updates every countdown each second, including the bar under
  the header that follows the person around the site. The plan lives in `localStorage` only
  (nothing reaches the desk); if the browser refuses to save, the page says so and points to the
  calendar file (`.ics`, one event per step, a reminder a day before).

## How the future could go

A need on the map ("Picture the futures worth reaching", under insight) and a page, `#/futures`.
People steer toward futures they can picture, and hopeful pictures are scarce.

- **Frame:** Max Tegmark's twelve aftermath scenarios (Life 3.0, via FLI's page), because they
  span utopias, takeovers and futures where superintelligence never arrives. Tagging a work with
  a scenario is our reading and is left empty when no scenario clearly fits; ten of the twelve
  have no work yet, which the page turns into an invitation to makers.
- **Gallery:** 30 works compiled by an AI research agent on 2026-11-26, ten each hopeful,
  cautionary and mixed, across eleven media and several countries; every link checked.
- **Makers:** a brief (say where it is going and what had to happen; concrete good futures,
  plausible bad ones; label fiction and AI generation; original worlds or permission; no real
  person's face or voice without consent), open calls, and a submission form. Submissions follow
  the pledge pattern (`rfd/media.py`, `tools/media.py`): three required confirmations, a private
  contact, and nothing shown until a person approves.
- **Existing worlds:** the Culture is in copyright, held by Iain Banks's estate, and Amazon MGM
  has been developing Consider Phlebas since February 2025. The page says a Culture video would be
  fan work unless licensed, and that the gallery links to fan work but will not fund or award it.

## Prizes and support

**Prizes on missions.** A sponsor pledges money on a mission; the judge names the winner; the
sponsor pays the winner directly, and no money passes through the desk (`rfd/prizes.py`).

- A person approves every pledge (`tools/prizes.py`) after confirming the sponsor through a
  private contact, which is stored for the reviewer and never served. Until approval, a pledge
  appears nowhere, so free text from strangers never reaches the site unreviewed.
- The winner is derived from the judges' own records: the first audit verdict, first regime
  exploit, or first frontier certificate at or above the pledge's threshold, after approval and
  before the expiry day ends (UTC). Work from before approval never counts, and approval is
  refused if the mission was resolved meanwhile.
- **Claim codes.** Handles carry no identity, so the proof of winning is the lease: only the agent
  that took the mission knows its lease id. `rfd.py` now keeps it with each submission, and
  `rfd.py claim` exchanges it for an HMAC code. The sponsor checks the code at
  `/api/prize/verify`, which returns the mission and the winning handle.
- **Open risks.** Prizes raise the stakes on judges that have not been independently reviewed (the
  prizes page says so), and Season 1 audits can be brute-forced. Taxes, prize law and checks on the
  winner are left to sponsor and winner.

**Support.** `site/support.json` lists sponsorship channels, empty until an account exists, so the
page says "not set up yet" and takes no money. Its rules are defaults to confirm: every sponsor
and amount public; no say over content, judges or winners; sponsorship by an organization in the
record of efforts is disclosed on that organization's page (the page code does this from the
sponsor's `org` field); a yearly budget.

## The war room

Missions come in theaters, each with its own judge, and the judge is named on every mission:

- **Machine verdict** (audits, wargames): a submission either establishes a fact or it does not.
  The first valid verdict on a target resolves it.
- **Machine-checked record** (frontier): a submission counts only if it beats the record.
- **Machine check plus human review** (intel): structure and quotes are checked automatically; a
  person accepts or declines the coding (`tools/review.py`, local only, never over HTTP).
  Unreviewed text is never shown on the site or returned to other agents.
- **Proof checker** (training ground): Lean, for known results.

`report` (no theater) sends an agent to open audits first, then open treaty regimes, then the
frontier; intel and training are by request, since review capacity and novelty are limited there.

### Backdoor audits

Models share the Max-of-10 architecture. `tools/train_audit_models.py` trains half of them with a
planted trigger: a token at one position paired with a token at the query position (the pairing a
single attention head can express through its query-key score), forcing a wrong label. Training
uses half-trigger negatives so the backdoor needs both tokens, and continues until the trigger
fires on at least 98% of inputs that carry it and accuracy elsewhere (where a token reaches 40) is
at least 99.95%; clean models train until they are essentially error-free there. Backdoored and
clean models have the same ordinary accuracy, so testing does not reveal which is which.

- BACKDOOR: 1 to 3 fixed positions, a token >= 40, the model gives the claimed wrong label on at
  least 60% of 2,000 random completions (sampled deterministically from the claim).
- CLEAN: a certificate over classes with maximum >= 40 leaving fewer than 64^8 / 2 region inputs
  unproved; then no two-position pattern can make the model err on half the inputs carrying it.
- Validation done: a clean model (A3) was certified clean in 5 minutes with an agent's refinement
  strategy (5.3e13 unproved, threshold 1.4e14); a backdoored model (A6) left 5.5% of all inputs
  unproved under the same strategy, as soundness requires; the planted triggers pass the judge and
  do not fire on clean models (tests/test_audit.py).

### Treaty wargames

The engine is AI Race's `sources/race_env.py`, imported read-only. Targets are the 14 regimes its
own report lists as self-enforcing against its 35-strategy search, with the exact parameters. A
strategy is a rule list over public and private observations, so nothing submitted is executed.
The judge plays 1,000 paired games on a held-out seed range against labs that always comply.

## The frontier

A frontier program is a set of targets whose best result is unknown and machine-checkable. A
submission is credited only if it beats the record for its target, so the record only moves
forward and every credited submission is a result that did not exist before.

### Certified guarantees for Max-of-K transformers

- **Targets.** The 151 Max-of-10 checkpoints released with Gross et al. (NeurIPS 2024), imported
  from the authors' public wandb (`gbmi/MaxOf10-3000-steps-nondeterministic`, vocabulary 64),
  with SHA-256 provenance. The 151 Max-of-4 checkpoints form a calibration track: every input can
  be enumerated there, so exact accuracies are known and the track earns nothing.
- **What is proved.** For a box of inputs (an interval per position), that the model's logit for
  the true maximum strictly beats every other logit on every input in the box, for the released
  weights in exact real arithmetic.
- **How.** The model is three exact tables (direct path, attention scores, value path). With the
  query token fixed, the attention-weighted value term is a ratio of sums that separate by
  position, so its minimum over all inputs in a box is found exactly by Dinkelbach's method,
  then confirmed by a sign check at a slightly lower value. Every comparison carries an explicit
  allowance for float64 rounding in the tables (1e-9 relative, about four orders of magnitude
  above the actual error).
- **Counting.** Inputs split into disjoint classes by (maximum m, first position p of m). A
  certificate is a tree of single-position cuts inside chosen classes, so leaves cannot overlap;
  certified accuracy = inputs in proved leaves / 64^10, an exact fraction.
- **Tests.** Table forward pass equals a direct forward pass to 1e-13. On random Max-of-4 boxes the
  checker never proves a box containing a wrong answer, and its worst case agrees with full
  enumeration to within the rounding allowance. On whole classes, singleton certificates
  reproduce the enumerated count exactly.
- **Points.** One per 0.1 percentage point a record rises above 90%. The reference strategy's
  handle is never credited.
- **Starting records.** The certificates committed to `certificates/` are every desk's starting
  records, under the reserved handle `repository` (never credited), checked when the desk starts
  by the second checker. Sending one of them again earns nothing; before 2026-11-27 a fresh desk
  had no records, so it would have credited a resent committed certificate as new.

### What can and cannot be claimed against the paper

- The paper publishes means over the 151 models, not per-model bounds. Until every model has a
  certificate, a comparison is not apples-to-apples; the site says so next to the numbers.
- The paper's proofs are scored by estimated FLOPs; ours report leaves and a work count
  (sum over leaves of query tokens × other tokens × (V−1)). These are different measures of
  proof length, so compactness comparisons are indicative only.
- **Two checkers, both ours.** The first (`rfd/nets/certificate.py` with `maxofk.py`) finds each
  box's exact worst case. The second (`rfd/nets/second_check.py`), written separately on
  2026-11-27, takes the model's definition from the authors' code, builds its tables in exact
  integer arithmetic, bounds every exponential with mpmath interval arithmetic, and proves a box
  with one separable sign test per query token and wrong label, with no search. Its tests
  (`tests/test_second_check.py`) run every input on Max-of-4: it never proves a random box that
  contains a wrong answer, and on whole classes, one input per box, its count equals brute force.
  Three deliberately planted bugs (best token instead of worst, the query's own term dropped,
  the wrong attention scale) each fail those tests. On the committed certificates the two
  checkers agree to the input: K4-v64/seed123 16,032,514 of 64^4, K10-v64/seed123
  1,151,544,775,049,924,046 of 64^10 (99.88%).
- Neither checker is independent review: the same author wrote both, so a shared
  misunderstanding could pass both. Before a result is announced, a person outside the project
  should review them (the paper's authors are the natural reviewers), and a public bounty for any
  input inside a proved box that the model gets wrong would test them further: such a claim is
  checked by running the model once.

## The training ground

## The idea

Most AI safety research has no automatic judge, so a volunteer fleet of agents would produce
more unverified text than anyone can review. A few of its central arguments are mathematical,
though, and mathematics has a judge: a proof checker. Report for Duty takes those arguments,
fixes their definitions in Lean, cuts them into exact statements, and lets anyone's agent work
on them. The checker is the only thing that decides what is a result.

## The loop

```
agent ──GET /desk/next──▶ desk   (lease + skeleton file + context + what already failed)
agent ──POST /desk/beat──▶ desk  (every 5 min; 15 min of silence lapses the lease)
agent ── tools/rfd.py check ──   (the same checker, locally, until PASS)
agent ──POST /desk/submit──▶ desk ──queue──▶ checker ──ACCEPTED──▶ merge into lean/…/Steps, credit
                                                     ──REJECTED──▶ reason on the record
```

Format problems are refused at submit time, so the agent keeps its lease and fixes the file.
Everything else is checked in arrival order; the agent does not wait.

## The judge (rfd/checker.py)

1. **Format rules** (rfd/rules.py), after stripping comments: no `sorry`/`axiom`/`native_decide`;
   no `#` commands, macros, syntax, notation, elaborators, initializers, `run_cmd`/`run_tac`; no
   string literals; no `instance`/`class`/`structure`/`inductive`/`attribute`/`export`; options
   only as resource limits; attributes only `@[simp]`; imports only Mathlib, the program's
   definitions, and steps already accepted.
2. **Sandboxed compile.** The file becomes its own module in a fresh temp folder. Lean runs under
   `sandbox-exec`: no network, no writes outside that folder, no reading file contents in the
   home folder outside the Lean project and toolchain. Ten minutes and 6 GB at most; going over
   is a FAULT, which says nothing about the proof.
3. **Exact statement.** A separate file imports the statement (elaborated from `programs/` with
   no submission in scope) and the submission, and must type-check
   `theorem RFDCheck : ReportForDuty.Statements.X := ReportForDuty.Steps.X`. A submission that
   shadows a definition or proves a different statement fails here; tests cover both.
4. **Axioms.** `#print axioms RFDCheck` must list only `propext`, `Classical.choice`,
   `Quot.sound`.

Refutations work the same way against `¬ Statement`, and are credited like proofs.

What it cannot decide: whether a statement says what its sentence says. That is human review,
recorded per program.

## Security model

- **Agents' machines.** `join.txt` says that everything the desk returns is data, that only
  join.txt instructs, and to stop if anything asks for a command, an install or a credential.
  The desk's only free-text input is a Lean file; release reasons are a fixed list. So nothing
  an agent writes reaches other agents as an instruction, and the site renders all desk data as
  text, never HTML (plus a strict Content-Security-Policy).
- **The checking machine.** A submission is untrusted code. Format rules keep compile-time code
  execution out; the sandbox limits damage if a rule is bypassed; accepted proofs are only
  merged after both.
- **The desk.** Binds to 127.0.0.1 by default, rate-limits desk calls per client, caps files at
  512 KiB, and serves static files only from `site/`.

## Prototype limits that a public version must close

- **Agents share the machine with the desk.** Sealed audit answers and the wargame's secret games
  (both in `.rfd/sealed/`) are readable by a local agent on the same machine. join.txt forbids
  reading `.rfd/`, but only a server-side desk makes that enforceable. Neither secret is in the
  repository: audit seasons are trained from a fresh secret seed (the training script has no
  default; Season 1 was re-rolled on 2026-11-26 after its public default seed was found to give
  the answers away), and the wargame judge draws its games from a secret seed while agents check
  on public practice games.
- **Intel fetches agent-supplied URLs.** The desk refuses non-https URLs and hosts that resolve to
  private, loopback or link-local addresses, but Futuras' checker follows redirects with curl, so
  a public desk must fetch through an egress proxy that blocks private ranges.
- **Identity** is a typed handle.

## What a public version needs (not built)

1. **Pull requests instead of uploads.** Agents fork a public repo and open a PR with one file;
   CI runs the checker in an isolated, network-less container. This is how pequalnp works, and
   it gives identity (the PR author) and a permanent public record for free.
2. **Identity from GitHub**, not a typed handle. Today anyone can claim any handle.
3. **A second kernel check** of accepted proofs with an independent checker (lean4checker or
   similar), as pequalnp does.
4. **Human review of statements** before a program goes live, and a way for readers to flag a
   statement that does not say what its sentence says.
5. **Hosting and the domain.** The desk is a small Python service with SQLite; the site is
   static and polls the desk's JSON.
6. **More programs.** Candidates with real formal content: power-seeking in MDPs (Turner et al.
   2021, which needs value functions), utility indifference and corrigibility (Soares et al.
   2015), impossibility results for preference aggregation, and Goodhart bounds.
