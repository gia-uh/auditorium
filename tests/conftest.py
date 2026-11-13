import pytest
import pytest_asyncio

from auditorium.testing import chromium_path


@pytest_asyncio.fixture
async def browser_page():
    playwright = pytest.importorskip("playwright.async_api")
    async with playwright.async_playwright() as p:
        kwargs = {}
        path = chromium_path()
        if path:
            kwargs["executable_path"] = path
        browser = await p.chromium.launch(**kwargs)
        context = await browser.new_context(viewport={"width": 800, "height": 600})
        page = await context.new_page()
        yield page
        await context.close()
        await browser.close()


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <link rel="stylesheet" href="/_auditorium/auditorium.css">
  <script type="module" src="/_auditorium/auditorium.js"></script>
  {head}
</head>
<body>
<main class="aud" data-format="{fmt}">
{body}
</main>
</body>
</html>
"""


def write_project(folder, body, fmt="explainer", head=""):
    """Write a one-file project: an index.html around ``body`` (its sections)."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.html").write_text(PAGE.format(body=body, fmt=fmt, head=head))
    return folder
