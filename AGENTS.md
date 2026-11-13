# auditorium

Auditorium turns a folder of plain HTML, CSS and JS into decks, posters, short
videos and pages. Time lives in the HTML as `data-` attributes; `auditorium.js`
builds a timeline from the DOM at load, and every surface (present, preview,
presenter, render, export) seeks that one timeline. The Python package is the
tool around the files: it serves, presents, previews, renders and exports them.
It is for agents and people who write HTML, including small models with nothing
but a shell and this CLI, and it is published on PyPI as `auditorium`.

This file changes when the goals change. Nothing in it should be made false by a
commit that adds code or content.

## What done means

- A change to the runtime or the file contract has a test that fails without it.
  Anything that depends on what the browser shows is tested through `seek(t)` in
  Chromium, on a project folder served by the real server; the render schedule
  is tested in pure Python.
- A new motion appears in `examples/motion`, and someone has looked at its
  rendered frames. A passing suite says the gallery moves, not that it reads.
- A user-visible change has a `CHANGELOG.md` entry and, if it changes how people
  write projects, a `Readme.md` update.
- `make test` and `make lint` pass, and `make docs` reports no new warnings.

## Where everything lives

| tier | holds |
|---|---|
| `AGENTS.md` | what the repo is, who it is for, what done means |
| `DESIGN.md` | the architecture, each rule with its reason, the non-goals |
| `docs/design/` | dated specs, for depth on one decision; `DESIGN.md` routes to them |
| `docs/plans/` | dated implementation plans, kept as history |
| `know-how/` | one procedure per job, with its traps |
| `Makefile`, `.rift.yaml`, `tests/` | every mechanical check, with its reason in a comment |
| module docstrings and file-head comments | what each module does and why it is shaped that way |
| `CHANGELOG.md`, git log | what changed and when |
| `examples/` | projects that double as living documentation |

## Working here

The gates are `make test`, `make lint` and `make docs` (`rift check` over the agent
docs). CI runs all three on every PR.

Print the know-how menu with `make know-how` (or `grep -m1 -H '^when:' know-how/*.md`)
and read the docs whose `when:` matches your task.

Work lands through the workspace default: an issue, a branch in a worktree, a PR,
and a squash merge on green CI. Trivial changes (a typo, a pinned version bump) go
straight to `main`. The author opens the PR and stops; Alex merges, or tells an
agent to.
