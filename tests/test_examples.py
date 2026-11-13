"""Every example is a project that builds, and the motion gallery moves."""
from pathlib import Path

import pytest

from auditorium.render import published_timeline

EXAMPLES = Path(__file__).parent.parent / "examples"


def example_projects():
    return sorted(p.parent for p in EXAMPLES.glob("*/index.html"))


def test_the_python_examples_are_gone():
    """5.0 has no Python authoring; an example deck.py would teach the old API."""
    assert not list(EXAMPLES.rglob("*.py"))


@pytest.mark.parametrize("path", example_projects(), ids=lambda p: p.name)
async def test_every_example_builds_a_timeline(path):
    published = await published_timeline(path)
    assert published["beats"], f"{path.name} built no beats"
    assert published["duration"] > 0


async def test_the_motion_gallery_uses_every_motion():
    """examples/motion is the motion library's living documentation: every
    entrance and idle the runtime knows appears in it."""
    import re

    runtime = (EXAMPLES.parent / "auditorium" / "static" / "auditorium.js").read_text()
    block = runtime[runtime.index("export const ENTRANCES"):runtime.index("// ---- build")]
    names = set(re.findall(r'^\s+"?([a-z-]+)"?:\s+\{ dur', block, re.MULTILINE))
    assert {"fade", "rise", "words", "count", "float", "ken-burns"} <= names
    page = (EXAMPLES / "motion" / "index.html").read_text()
    for name in names:
        assert re.search(rf'data-(enter|exit|idle)="{name}"', page), f"the gallery does not show {name}"
