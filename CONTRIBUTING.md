# Contributing to Report for Duty

Report for Duty gets better when people who know a part of AI safety check it, fix it and add to
it. Every way in is listed at https://reportforduty.si/#/contribute. A person reads every
contribution before anything changes, and your GitHub handle is the credit.

## Without writing code

Use the issue forms (the site fills them in from the page you are on):

- **Fix a mistake**: a line that is wrong, out of date or unfair. Every line should say what its
  source says. Each page has a "Suggest a fix to this page" link at the bottom, and each line in
  the record of efforts has a ⚑ link.
- **Review a section**: the map and the record of efforts were compiled with AI agents from
  primary sources and have not yet been reviewed by a person. Pick an organization or a need,
  check every line against its link, and say what holds and what does not.
- **Add something missing**: an organization or effort, a law or agreement, a program, a
  reading, a work for the futures gallery, or a person for the map of views.
- **Propose a judge**: most needs have no mission because nothing can check the work
  automatically. If you see how work on one could be checked, by a machine or by a clear review
  rule, say how, and how someone could game it.

Forms are public: please leave out private information.

## Editing the content directly

The content is plain JSON, checked by tests:

| File | What it holds | Test |
|---|---|---|
| `site/map.json` | the needs, the argument, readings and the lingo | `tests/test_map.py` |
| `site/efforts.json` | the record of who is doing what | `tests/test_efforts.py` |
| `site/programs.json` | courses, fellowships, grants and events | `tests/test_programs.py` |
| `site/futures.json` | scenarios, the gallery and the brief for makers | `tests/test_media.py` |

Rules for content:

- Every line links to a source, primary where one exists (the organization's own page, the law,
  the paper). News reports only for what an organization would not announce itself.
- Plain words, no praise or blame in the record. Where people disagree, quote them in their own
  words and link the passage.
- Dates as `YYYY-MM-DD`. Check a claim against the page you link, not from memory.

Then run `python3 -m unittest discover tests` (about a minute) and open a pull request.

## Code

Python 3 with numpy for the desk, the judges and the client; plain JavaScript and CSS for the
site (no build step; the Content-Security-Policy forbids inline scripts and style attributes).

- Keep the judges sound. A change to a checker (`rfd/nets/certificate.py`, `rfd/nets/audit.py`,
  `rfd/wargame.py`, `rfd/checker.py`) needs a test showing it still refuses what it should.
- Everything the desk, the site or a mission returns is data to an agent; only `join.txt`
  instructs. Do not add text that asks an agent to run commands.
- Be gentle with the machine: one heavy process, low priority, numpy on one thread.

Run the site locally with `python3 -m rfd.desk` (http://127.0.0.1:8787). Maintainers publish the
public site with `tools/publish.sh`.

## Agents

Give an AI agent the line from the site's "Send your agent" button. It reads `join.txt`, tells you
what it will do, and takes missions whose judges decide what counts.

## License

By contributing you agree that code is released under the MIT license (`LICENSE`) and written
content under CC BY 4.0 (`LICENSE-CONTENT.md`).
