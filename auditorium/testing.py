"""Which Chromium the test suite, render and export launch."""
from __future__ import annotations

import os


def chromium_path() -> str | None:
    """Return an explicit Chromium executable path, or None to let Playwright choose.

    Returns None by default: Playwright >= 1.62 installs a Chromium that works
    on Ubuntu 26.04, and letting it resolve its own browser is what keeps the
    suite portable.

    Deliberately NOT auto-detecting a cached build. Older Playwright versions
    left stale browsers in ~/.cache/ms-playwright, and silently preferring one
    would run the whole suite against a browser that is not the one under test
    — a passing suite proving nothing about the browser users actually get.
    Set AUDITORIUM_CHROMIUM to override on a host where the download fails.
    """
    return os.environ.get("AUDITORIUM_CHROMIUM") or None
