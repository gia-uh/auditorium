"""Screenshots the book takes of auditorium's own pages while it builds.

Each chapter that shows a surface (the preview, the editor, the presenter
view) calls ``shot()`` from a hidden block: it serves a project with the real
CLI on a free port, opens one page in Chromium, waits for it to settle, saves
a PNG under ``build/img/`` and returns it as a PIL image, which the book shows.
Nothing here is pasted by hand, so a change to a surface changes the book.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def shot(project: str, path: str = "/preview", name: str = "shot", *, edit: bool = False,
         run: bool = False, size=(1440, 900), wait: float = 1.5, keys=(), actions=None) -> Image.Image:
    """Serve ``project``, open ``path``, press ``keys`` and return what Chromium shows.

    ``actions(page)``, when given, runs after the keys, for a click or a seek.
    """
    port = _free_port()
    cmd = [sys.executable, "-m", "auditorium", "run" if run else "preview", project,
           "--port", str(port), "--no-open", "--no-watch"]
    if run:
        cmd.append("--presenter")
    if edit:
        cmd.append("--edit")
    server = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        url = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                urllib.request.urlopen(url + "/", timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        out = Path("build/img") / f"{name}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": size[0], "height": size[1]})
            page.goto(url + path, wait_until="networkidle")
            page.wait_for_timeout(int(wait * 1000))
            for key in keys:
                page.keyboard.press(key)
                page.wait_for_timeout(700)
            if actions:
                actions(page)
                page.wait_for_timeout(500)
            page.screenshot(path=str(out))
            browser.close()
        return Image.open(out)
    finally:
        server.terminate()
        server.wait(timeout=10)
