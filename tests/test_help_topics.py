"""The help topics of #88 (section 09 of the 2026-11-10 spec): start, formats,
attributes and templates, and what holds for every topic.

The topics are the only doc an agent with the CLI needs, so the tests tie each
claim to the code it describes: a command it names exists, a format's stage
and safe area are the runtime's, an attribute the runtime reads is taught, a
template that ships is listed, and every HTML snippet builds in Chromium.
"""
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from auditorium.cli import app
from auditorium.help import topic_path, topics
from auditorium.templates import templates

from conftest import write_project
from test_layouts import OUTSIDE, SAFE, STAGE, classes_in, write_assets
from test_templates import known_class

ROOT = Path(__file__).parent.parent
RUNTIME = (ROOT / "auditorium" / "static" / "auditorium.js").read_text()
NEW = ["start", "formats", "attributes", "templates"]

# test_layouts' safe-area probe, except the anchored-line overlay's own box: it
# covers its section by design, as the layer lines are drawn in. The lines in
# it are still measured.
OUTSIDE_CONTENT = OUTSIDE.replace(
    "if (el.closest('aside.notes')) continue;",
    "if (el.closest('aside.notes') || el.classList.contains('aud-overlay')) continue;")
assert OUTSIDE_CONTENT != OUTSIDE


def text(topic):
    return topic_path(topic).read_text()


def html_snippets(topic):
    return re.findall(r"```html\n(.*?)```", text(topic), re.DOTALL)


def commands():
    """Every command and subcommand the CLI has, as 'name' or 'group sub'."""
    import typer.main

    cli = typer.main.get_command(app)
    out = set()
    for name, cmd in cli.commands.items():
        out.add(name)
        for sub in getattr(cmd, "commands", {}):
            out.add(f"{name} {sub}")
    return out


def test_the_new_topics_ship():
    assert set(NEW) <= set(topics())


@pytest.mark.parametrize("topic", sorted(topics()))
def test_every_topic_stays_under_150_lines(topic):
    assert len(text(topic).splitlines()) < 150


@pytest.mark.parametrize("topic", sorted(topics()))
def test_every_command_a_topic_names_exists(topic):
    """Help describes the installed version: a command it shows that the CLI
    does not have sends an agent into an error it cannot fix."""
    known = commands()
    groups = {c.split()[0] for c in known if " " in c}
    named = re.findall(r"auditorium ([a-z]+)(?: ([a-z]+))?", text(topic))
    wrong = sorted({f"{a} {b}".strip() for a, b in named
                    if a not in known or (a in groups and b and f"{a} {b}" not in known)})
    assert wrong == []


def test_bare_help_shows_start_then_lists_every_topic():
    """Section 09: start is "shown by bare auditorium help"."""
    result = CliRunner().invoke(app, ["help"])
    assert result.exit_code == 0
    assert result.output.startswith(text("start"))
    listing = result.output[len(text("start")):]
    for topic in topics():
        assert re.search(rf"^{topic} ", listing, re.MULTILINE), f"{topic} not listed"
    assert result.output.splitlines()[-1].startswith(f"{len(topics())} topics")


def test_help_all_with_a_topic_is_refused():
    result = CliRunner().invoke(app, ["help", "--all", "start"])
    assert result.exit_code == 1
    assert "--all" in result.output


def test_help_all_prints_every_topic_and_ends_on_a_count():
    result = CliRunner().invoke(app, ["help", "--all"])
    assert result.exit_code == 0
    for topic in topics():
        assert text(topic) in result.output
    assert result.output.splitlines()[-1] == f"{len(topics())} topics"


# ---- each topic against the code it describes ---------------------------------


def test_start_is_the_loop_in_ten_lines():
    """Section 09: the loop in ten lines, so bare help is enough to begin.
    The loop is the numbered list; the rules after it are not the loop."""
    loop = re.search(r"^1\. .*?(?=\n\n)", text("start"), re.MULTILINE | re.DOTALL).group(0)
    assert len(loop.splitlines()) <= 10
    for step in ["auditorium template new", "auditorium preview", "auditorium export"]:
        assert step in loop


def runtime_formats():
    block = RUNTIME[RUNTIME.index("export const FORMATS"):RUNTIME.index("};", RUNTIME.index("export const FORMATS"))]
    out = {}
    for name, w, h in re.findall(r"^\s+(\w+):\s+\{ w: (\d+), h: (\d+)", block, re.MULTILINE):
        out[name] = (int(w), int(h))
    out["page"] = None
    return out


def test_formats_gives_each_format_its_stage_and_safe_area():
    rows = {}
    for m in re.finditer(r"^\| (\w+) \|.*$", text("formats"), re.MULTILINE):
        rows.setdefault(m.group(1), m.group(0))  # the first table: stages
    for name, stage in runtime_formats().items():
        assert name in rows, f"no row for {name}"
        if stage:
            assert f"{stage[0]} × {stage[1]}" in rows[name]
            top, right, bottom, left = SAFE[name]
            assert f"{top} {right} {bottom} {left}" in rows[name]


def runtime_attributes():
    found = set(re.findall(r'"(data-[a-z]+)"', RUNTIME))
    found |= set(re.findall(r"\[(data-[a-z]+)\]", RUNTIME))
    # Marks the runtime writes on what it built, not attributes an author sets.
    return {a for a in found if not a.startswith("data-aud")}


def test_attributes_teaches_every_attribute_the_runtime_reads():
    taught = set(re.findall(r"`(data-[a-z]+)", text("attributes")))
    assert runtime_attributes() - taught == set()


def test_templates_lists_every_bundled_theme():
    """An agent with only a shell cannot list /_auditorium/themes/."""
    from auditorium.templates import themes

    line = re.search(r"^Themes: (.*?)\.$", text("templates"), re.MULTILINE | re.DOTALL)
    assert line, "no 'Themes: ...' line"
    assert sorted(n.strip() for n in line.group(1).replace("\n", " ").split(",")) == themes()


def test_templates_names_every_template_and_its_formats():
    body = text("templates")
    for name, meta in templates().items():
        row = re.search(rf"^\| {name} \|.*$", body, re.MULTILINE)
        assert row, f"no row for {name}"
        for fmt in meta["formats"]:
            assert fmt in row.group(0)


# ---- every snippet builds ------------------------------------------------------


def snippet_cases():
    for topic in NEW:
        for i, snippet in enumerate(html_snippets(topic)):
            yield pytest.param(topic, snippet, id=f"{topic}-{i}")


@pytest.mark.parametrize("topic,snippet", list(snippet_cases()))
def test_every_class_a_snippet_uses_is_defined(topic, snippet):
    assert sorted(c for c in classes_in(snippet) if not known_class(c)) == []
    assert "data-placeholder" not in snippet


@pytest.mark.parametrize("topic,snippet", list(snippet_cases()))
async def test_every_snippet_builds(browser_page, served, tmp_path, topic, snippet):
    """A snippet is either beats (sections) or a whole <main>. Placed in a
    project of its format, it builds with no error and at least one beat."""
    main = re.search(r'<main class="aud" data-format="(\w+)">(.*)</main>', snippet, re.DOTALL)
    fmt, body = (main.group(1), main.group(2)) if main else ("deck", snippet)
    folder = write_project(tmp_path / topic, body, fmt=fmt)
    write_assets(folder, body)
    errors = []
    browser_page.on("pageerror", lambda e: errors.append(str(e)))
    if fmt in STAGE:
        await browser_page.set_viewport_size({"width": STAGE[fmt][0], "height": STAGE[fmt][1]})
    await browser_page.goto(served(folder) + "/?embed")
    await browser_page.wait_for_function("() => window.auditorium && window.auditorium.built === true")
    assert errors == []
    assert await browser_page.evaluate("() => window.auditorium.beats.length") >= 1
    # As help layouts and components: on a stage, every box stays in the safe area.
    if fmt in SAFE:
        assert await browser_page.evaluate(OUTSIDE_CONTENT, list(SAFE[fmt])) == []
