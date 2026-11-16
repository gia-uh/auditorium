"""``auditorium check`` (#80, rescoped by section 08 of the 2026-11-10 spec).

Every rule has a fixture in tests/rules/NAME that breaks it, and the suite
fails if a rule does not fire on its fixture at the line that breaks it, or
fires on any template example or example project. The help page of each rule
is held to the same standard: its broken snippet fires the rule and its fixed
snippet passes.
"""
import json
import re
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from auditorium.check import RULES, check, reading
from auditorium.check.source import annotate, parse
from auditorium.cli import app
from auditorium.help import rule_path
from auditorium.templates import TEMPLATES

from conftest import write_narration, write_project

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "rules"
AUDIT = (ROOT / "auditorium" / "check" / "audit.js").read_text()

STRUCTURE = sorted(n for n, r in RULES.items() if r.group == "structure")
LAYOUT = sorted(n for n, r in RULES.items() if r.group == "layout")

# Where each fixture breaks its rule: the file and line a finding must name.
WHERE = {
    "parse": ("index.html", 15), "unknown-name": ("index.html", 15),
    "external-url": ("index.html", 15), "missing-asset": ("index.html", 15),
    "wall-clock": ("script.js", 3), "bare-transition": ("theme.css", 2),
    "time-attrs": ("index.html", 14), "duration": ("index.html", 10),
    "duplicate-id": ("index.html", 16), "overrun": ("index.html", 14),
    "cue-missing": ("index.html", 13),
    "overflow": ("index.html", 15), "overlap": ("index.html", 17),
    "off-grid": ("index.html", 16), "safe-area": ("index.html", 15),
    "min-size": ("index.html", 15), "contrast": ("index.html", 15),
    "console-error": ("index.html", 18), "h-scroll": ("index.html", 15),
    "placeholder": ("index.html", 15), "placeholder-asset": ("index.html", 15),
    "empty": ("index.html", 14), "pop-in": ("index.html", 15),
    "reading-time": ("index.html", 14), "dead-air": ("index.html", 14),
}

CLEAN = sorted([*TEMPLATES.glob("*/example"), *(ROOT / "examples").iterdir()])


# ---- the registry --------------------------------------------------------------


def test_every_rule_has_a_fixture_a_help_page_and_a_place():
    assert sorted(p.name for p in FIXTURES.iterdir() if p.is_dir()) == sorted(RULES)
    assert set(WHERE) == set(RULES)
    for name in RULES:
        assert rule_path(name).is_file(), name


def test_the_layout_rules_are_the_ones_the_browser_measures():
    """audit.js measures most layout rules; console-error is the page's own
    log, placeholder and placeholder-asset need only the source and
    assets.yaml, all read in Python, and reading.py judges reading-time and
    dead-air from what audit.js counts."""
    measured = set(re.search(r"const RULES = \[(.*?)\]", AUDIT).group(1).replace('"', "").replace(" ", "").split(","))
    python = {"console-error", "placeholder", "placeholder-asset", "reading-time", "dead-air"}
    assert measured | python == set(LAYOUT)


# ---- each rule fires on its fixture, at its line --------------------------------


@pytest.mark.parametrize("rule", STRUCTURE)
def test_a_structure_rule_fires_on_its_fixture_without_a_browser(rule):
    report = check(FIXTURES / rule, layout=False)
    hits = [(f.file, f.line) for f in report.findings if f.rule == rule]
    assert WHERE[rule] in hits, report.text()


@pytest.mark.parametrize("rule", LAYOUT)
def test_a_layout_rule_fires_on_its_fixture(rule):
    report = check(FIXTURES / rule)
    assert report.passes == ["structure", "layout"]
    hits = [(f.file, f.line) for f in report.findings if f.rule == rule]
    assert WHERE[rule] in hits, report.text()


def test_a_finding_carries_what_was_measured_and_the_fix():
    f = next(f for f in check(FIXTURES / "overflow").findings if f.rule == "overflow")
    assert f.selector == 'section[data-beat="broken"] h1'
    assert f.beat == "broken" and f.t is not None
    assert re.search(r"\d+ px", f.message)
    assert f.fix


def test_structure_errors_stop_the_layout_pass():
    """A broken tree moves every box: measuring it would only add noise."""
    report = check(FIXTURES / "parse")
    assert report.passes == ["structure"]
    assert "layout not run" in report.summary()


@pytest.mark.parametrize("fmt, lengths, fires", [
    ("short", [10, 5], False), ("short", [30, 30], False), ("short", [40, 21], True),
    ("short", [7, 7.9], True), ("explainer", [5], False), ("deck", [], False),
])
def test_duration_holds_a_short_to_15_to_60_seconds(fmt, lengths, fires, tmp_path):
    body = "".join(f'<section data-beat="b{i}" data-d="{d}" class="statement"><p>Beat</p></section>'
                   for i, d in enumerate(lengths)) or '<section class="statement"><p>Beat</p></section>' * 3
    report = check(write_project(tmp_path, body, fmt=fmt), layout=False)
    assert ("duration" in {f.rule for f in report.findings}) is fires, report.text()


@pytest.mark.parametrize("fmt", ["square", "portrait", "story"])
def test_duration_points_at_a_posters_second_beat(fmt, tmp_path):
    body = '<section data-beat="one"><p>A</p></section>\n<section data-beat="two"><p>B</p></section>'
    hits = [f for f in check(write_project(tmp_path, body, fmt=fmt), layout=False).findings if f.rule == "duration"]
    assert [f.beat for f in hits] == ["two"]


# ---- and on nothing that is right ---------------------------------------------


@pytest.mark.parametrize("folder", CLEAN, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_every_template_example_and_example_passes_with_zero_findings(folder):
    report = check(folder)
    assert report.findings == [], report.text()


def test_a_fresh_template_fails_on_its_placeholders_only(tmp_path):
    result = CliRunner().invoke(app, ["template", "new", "talk", str(tmp_path / "talk")])
    assert result.exit_code == 0, result.output
    report = check(tmp_path / "talk")
    assert report.findings
    assert {f.rule for f in report.findings} == {"placeholder"}, report.text()


# ---- the help pages ------------------------------------------------------------


def snippet(rule, which):
    text = rule_path(rule).read_text()
    return re.search(rf"## {which}\n\n```html\n(.*?)```", text, re.DOTALL).group(1)


# The format a rule's help snippets are checked in, where a deck cannot break it.
SNIPPET_FORMAT = {"duration": "square"}


@pytest.mark.parametrize("rule", STRUCTURE)
def test_a_structure_rules_help_snippets_break_and_fix_it(rule, tmp_path):
    fmt = SNIPPET_FORMAT.get(rule, "deck")
    broken = write_project(tmp_path / "broken", snippet(rule, "Broken"), fmt=fmt)
    fixed = write_project(tmp_path / "fixed", snippet(rule, "Fixed"), fmt=fmt)
    for folder in (broken, fixed):
        # Snippets name assets/ files as a real project would hold them.
        for rel in re.findall(r'src="(assets/[^"]+)"', (folder / "index.html").read_text()):
            if folder is fixed:
                (folder / rel).parent.mkdir(parents=True, exist_ok=True)
                (folder / rel).write_bytes(b"")
        # A narrated snippet says "Small steps win" in a 1.2 s clip.
        for rel in re.findall(r'data-say="assets/vo/([^"]+)\.json"', (folder / "index.html").read_text()):
            write_narration(folder, rel, [("Small", 0.0), ("steps", 0.4), ("win.", 0.8)], 1.2, rate=4000)
    assert rule in {f.rule for f in check(broken, layout=False).findings}
    assert check(fixed, layout=False).findings == []


# placeholder-asset turns on assets.yaml, which a snippet of HTML cannot carry;
# its fixture and tests/test_assets.py hold it. The reading rules need a clock,
# which a deck has not; they are checked on an explainer below.
READING = ["reading-time", "dead-air"]
SNIPPET_LAYOUT = [r for r in LAYOUT if r != "placeholder-asset" and r not in READING]


@pytest.mark.parametrize("rule", READING)
def test_a_reading_rules_help_snippets_break_and_fix_it(rule, tmp_path):
    broken = check(write_project(tmp_path / "broken", snippet(rule, "Broken")))
    fixed = check(write_project(tmp_path / "fixed", snippet(rule, "Fixed")))
    assert rule in {f.rule for f in broken.findings}, broken.text()
    assert fixed.findings == [], fixed.text()


def test_the_layout_rules_fixed_snippets_pass_together(tmp_path):
    body = "\n".join(snippet(r, "Fixed") for r in SNIPPET_LAYOUT)
    report = check(write_project(tmp_path / "fixed", body, fmt="deck"))
    assert report.findings == [], report.text()


def test_the_layout_rules_broken_snippets_fire_together(tmp_path):
    """h-scroll needs a page, and placeholder has its fixture; the rest share
    one deck, and each must still fire."""
    rules = [r for r in SNIPPET_LAYOUT if r != "h-scroll"]
    body = "\n".join(snippet(r, "Broken") for r in rules)
    report = check(write_project(tmp_path / "broken", body, fmt="deck"))
    assert set(rules) <= {f.rule for f in report.findings}, report.text()


def test_help_rule_prints_one_rule_and_lists_them_all():
    one = CliRunner().invoke(app, ["help", "rule", "overflow"])
    assert one.exit_code == 0
    assert one.output == rule_path("overflow").read_text()
    listing = CliRunner().invoke(app, ["help", "rule"])
    assert listing.output.splitlines()[-1].startswith(f"{len(RULES)} rules")
    wrong = CliRunner().invoke(app, ["help", "rule", "overlpa"])
    assert wrong.exit_code == 1 and "overlap" in wrong.output


# ---- the command ---------------------------------------------------------------


def test_check_prints_the_first_errors_and_ends_on_the_counts(tmp_path):
    ids = "\n".join(f'    <p id="same">Line {i}</p>' for i in range(11))
    folder = write_project(tmp_path / "p", f'  <section data-beat="a" class="title">\n{ids}\n  </section>',
                           fmt="deck")
    result = CliRunner().invoke(app, ["check", str(folder)])
    assert result.exit_code == 1
    lines = result.output.splitlines()
    assert len(re.findall(r"^index\.html:\d+  duplicate-id  error", result.output, re.MULTILINE)) == 8
    assert "... 2 more in dist/check.json" in result.output
    assert lines[-1].startswith("10 errors, 0 warnings")
    saved = json.loads((folder / "dist" / "check.json").read_text())
    assert saved["errors"] == 10 and len(saved["findings"]) == 10


def test_check_json_prints_every_finding(tmp_path):
    folder = shutil.copytree(FIXTURES / "duplicate-id", tmp_path / "p")
    result = CliRunner().invoke(app, ["check", str(folder), "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["findings"][0]["rule"] == "duplicate-id"
    assert set(data["findings"][0]) >= {"rule", "level", "file", "line", "selector", "beat", "t", "message", "fix"}


def test_check_exits_zero_on_a_clean_project(tmp_path):
    folder = shutil.copytree(TEMPLATES / "poster" / "example", tmp_path / "poster")
    result = CliRunner().invoke(app, ["check", str(folder)])
    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[-1].startswith("0 errors, 0 warnings")


# ---- live data, offline ----------------------------------------------------------

FETCH = """  <section data-beat="sales" class="title">
    <h1 id="v">0</h1>
    <script type="module">
      const r = await fetch("https://example.com/api/sales.json");
      document.getElementById("v").textContent = (await r.json()).value;
    </script>
  </section>"""


def test_a_declared_endpoint_is_answered_from_its_fixture(tmp_path):
    folder = write_project(tmp_path / "p", FETCH, fmt="deck")
    (folder / "assets").mkdir()
    (folder / "assets" / "sales.json").write_text('{"value": 18}')
    (folder / "auditorium.toml").write_text(
        '[data.sales]\nurl = "https://example.com/api/sales.json"\nfixture = "assets/sales.json"\n')
    report = check(folder)
    assert report.findings == [], report.text()


def test_an_undeclared_endpoint_is_an_external_url(tmp_path):
    folder = write_project(tmp_path / "p", FETCH, fmt="deck")
    report = check(folder)
    assert [f.rule for f in report.findings] == ["external-url"]


# ---- the source parser ----------------------------------------------------------


def test_html_a_browser_reads_as_written_has_no_parse_problems():
    """Optional end tags and SVG's self-closing shapes are valid, not repairs."""
    ok = parse('<ul><li>one<li>two</ul><p>a<p>b<svg><path d="M0 0"/></svg><br><img src="x">')
    assert ok.problems == []


@pytest.mark.parametrize("html, line", [
    ("<div>\n<span>\n</div>", 2),            # <span> closed by </div>
    ("<p>a\n<div>b</div>\n</p>", 1),         # the <div> leaves the <p>
    ("<div/>\n<p>x</p>", 1),                 # <div/> does not close in HTML
    ("<section>\n<h1>x</h1>", 1),            # never closed
])
def test_a_repair_is_reported_at_the_line_that_causes_it(html, line):
    problems = parse(html).problems
    assert problems and problems[0][0] == line


def test_annotate_marks_every_element_with_its_line_and_keeps_the_lines():
    page = (TEMPLATES / "talk" / "example" / "index.html").read_text()
    marked = annotate(page)
    assert marked.count("\n") == page.count("\n")
    for number, (before, after) in enumerate(zip(page.splitlines(), marked.splitlines()), 1):
        tags = len(re.findall(r"<[a-zA-Z]", before))
        assert after.count(f'data-aud-line="{number}"') == tags


def test_an_unknown_layer_is_an_unknown_name(tmp_path):
    body = '<div data-layer="backdrop"></div>\n<section data-beat="b" data-d="2"><p>Beat</p></section>'
    hits = [f for f in check(write_project(tmp_path, body), layout=False).findings if f.rule == "unknown-name"]
    assert [f.fix for f in hits] == ['set data-layer="background"']


def test_unknown_emphasis_ambient_and_grade_names_are_unknown_names(tmp_path):
    body = ('<div data-layer="background" data-ambient="aurorra"></div>\n'
            '<section data-beat="b" data-d="2"><p data-emphasis="focs">Beat</p></section>\n'
            '<div data-layer="grade" data-grade="vignette grian"></div>')
    hits = [f for f in check(write_project(tmp_path, body), layout=False).findings if f.rule == "unknown-name"]
    assert sorted(f.fix for f in hits) == ['set data-ambient="aurora"', 'set data-emphasis="focus"',
                                         'set data-grade="grain"']


# ---- the reading rules ---------------------------------------------------------


@pytest.mark.parametrize("words, hold, narrated, expected", [
    (5, 3.5, False, None), (5, 2.5, False, "short"), (5, 1.4, False, "error"),
    (5, 10, False, "long"), (5, 10, True, None), (0, 30, False, None),
])
def test_reading_time_is_two_sided(words, hold, narrated, expected):
    """5 words need 2 s plus 1.5 s: 3.5 s fits, 2.5 s is 0.71 of it, 1.4 s
    is 0.4, 10 s is 2.9 times it, unless a voice holds the beat."""
    assert reading.verdict(words, hold, reading.pace({}, "en"), narrated) == expected


def test_reading_pace_is_per_language():
    config = {"reading": {"base": 1.0, "es": {"rate": 2.0}, "es-cu": {"base": 2.0}}}
    assert reading.pace({}, None) == reading.Pace(2.5, 1.5)
    assert reading.pace(config, "en") == reading.Pace(2.5, 1.0)
    assert reading.pace(config, "es") == reading.Pace(2.0, 1.0)
    assert reading.pace(config, "es-CU") == reading.Pace(2.0, 2.0)


def test_still_stretches_are_what_no_motion_or_voice_covers():
    assert reading.still(0, 10, [(1, 2), (6, 7)], 3) == [(2, 6)]
    assert reading.still(0, 10, [(1, 2), (6, 7)], 2.5) == [(2, 6), (7, 10)]
    assert reading.still(0, 10, [(1, 2), (5, None)], 2.5) == [(2, 5)]
    assert reading.still(0, 10, [(-5, None)], 0) == []


def test_reading_time_follows_the_projects_language(tmp_path):
    """Six words fit 4 s at the default pace; a Spanish pace of one word a
    second plus 6 s needs 12 s, three times the beat."""
    body = '<section data-beat="b" class="statement" data-d="4"><p data-idle="float">' + "palabra " * 6 + "</p></section>"
    folder = write_project(tmp_path, body)
    html = folder / "index.html"
    html.write_text(html.read_text().replace('lang="en"', 'lang="es"'))
    assert [f for f in check(folder).findings if f.rule == "reading-time"] == []
    (folder / "auditorium.toml").write_text("[reading.es]\nrate = 1\nbase = 6\n")
    hits = [f for f in check(folder).findings if f.rule == "reading-time"]
    assert [f.level for f in hits] == ["error"], hits


def test_dead_air_counts_a_track_function_as_motion(tmp_path):
    """No animation runs in this beat, but script.js draws on every seek."""
    body = ('<section data-beat="b" class="statement" data-d="6"><p id="n">0</p></section>')
    folder = write_project(tmp_path, body, head='<script type="module" src="script.js"></script>')
    (folder / "script.js").write_text(
        "auditorium.track((s) => { document.getElementById('n').textContent = s.toFixed(1); }, {beat: 'b'});\n")
    assert "dead-air" not in {f.rule for f in check(folder).findings}
    (folder / "script.js").write_text("auditorium.track(() => {}, {beat: 'b'});\n")
    assert "dead-air" in {f.rule for f in check(folder).findings}
