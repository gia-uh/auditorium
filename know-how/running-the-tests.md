---
when: running the test suite on a new machine or worktree, browser tests fail to launch Chromium, or render tests are skipped
---

# Running the tests

```bash
uv sync
uv run playwright install chromium
make test
```

On the VPS on 2026-10-10 the suite ran 203 tests in 73 s. With no ffmpeg on the
machine, 12 of them skipped: the encode, audio and render CLI tests need `ffmpeg`
and `ffprobe` on `PATH`. A green run with skips has not tested rendering. CI
installs both and fails before the tests if either is missing.

## Traps

- **`playwright install` deletes browsers it thinks nobody uses.** The cache in
  `~/.cache/ms-playwright` is shared by every project on the machine, and
  Playwright removes any build not referenced by a registered install. On
  2026-10-10, installing this repo's Chromium (build 1234) deleted build 1243,
  which another repo's virtualenv on the same host still needed. If another
  project's browser tests start failing with "Executable doesn't exist", run
  `.venv/bin/python -m playwright install chromium` in that project.
- **A fresh worktree has the wrong Playwright browser, or none.** Each Playwright
  version pins one Chromium build, so run `playwright install` inside the
  worktree's own environment, not the main checkout's.
- **`AUDITORIUM_CHROMIUM` overrides the browser** for the tests, render and
  export, on a host where Playwright cannot download one or where installing
  would delete a build another project needs. Nothing auto-detects a cached build; `auditorium/testing.py`
  explains why.
- **A test that hangs at 0% CPU may be two sockets on two event loops.** Starlette's
  `TestClient` used without `with` runs every `websocket_connect` on its own
  event-loop thread, and a message relayed between two sockets can then be lost,
  leaving a `receive_json()` that never returns. `tests/test_server.py` hung in up
  to 2 runs in 5 that way until its clients were entered with `with`. Any new test
  that connects more than one socket must share one client the same way.
