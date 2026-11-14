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

from auditorium.check import RULES, check
from auditorium.check.source import annotate, parse
from auditorium.cli import app
from auditorium.help import rule_path
from auditorium.templates import TEMPLATES

from conftest import write_project

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
    "time-attrs": ("index.html", 14), "duplicate-id": ("index.html", 16),
    "overflow": ("index.html", 15), "overlap": ("index.html", 17),
    "off-grid": ("index.html", 16), "safe-area": ("index.html", 15),
    "min-size": ("index.html", 15), "contrast": ("index.html", 15),
    "console-error": ("index.html", 18), "h-scroll": ("index.html", 15),
    "placeholder": ("index.html", 15), "empty": ("index.html", 14),
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
    log and placeholder needs only the source, both read in Python."""
    measured = set(re.search(r"const RULES = \[(.*?)\]", AUDIT).group(1).replace('"', "").replace(" ", "").split(","))
    assert measured | {"console-error", "placeholder"} == set(LAYOUT)


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


@pytest.mark.parametrize("rule", STRUCTURE)
def test_a_structure_rules_help_snippets_break_and_fix_it(rule, tmp_path):
    broken = write_project(tmp_path / "broken", snippet(rule, "Broken"), fmt="deck")
    fixed = write_project(tmp_path / "fixed", snippet(rule, "Fixed"), fmt="deck")
    for folder in (broken, fixed):
        # Snippets name assets/ files as a real project would hold them.
        for rel in re.findall(r'src="(assets/[^"]+)"', (folder / "index.html").read_text()):
            if folder is fixed:
                (folder / rel).parent.mkdir(parents=True, exist_ok=True)
                (folder / rel).write_bytes(b"")
    assert rule in {f.rule for f in check(broken, layout=False).findings}
    assert check(fixed, layout=False).findings == []


def test_the_layout_rules_fixed_snippets_pass_together(tmp_path):
    body = "\n".join(snippet(r, "Fixed") for r in LAYOUT)
    report = check(write_project(tmp_path / "fixed", body, fmt="deck"))
    assert report.findings == [], report.text()


def test_the_layout_rules_broken_snippets_fire_together(tmp_path):
    """h-scroll needs a page, and placeholder has its fixture; the rest share
    one deck, and each must still fire."""
    rules = [r for r in LAYOUT if r != "h-scroll"]
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
