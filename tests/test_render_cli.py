import re
import shutil

import pytest
from typer.testing import CliRunner

from auditorium.cli import app

runner = CliRunner()


def test_render_command_exists_and_documents_itself():
    result = runner.invoke(app, ["render", "--help"])
    assert result.exit_code == 0
    # Rich colours the help when it detects CI (GITHUB_ACTIONS is enough), and
    # the escape codes split "--fps" into "-" and "-fps". Match the plain text.
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
    for flag in ["--fps", "--size", "--format", "--audio"]:
        assert flag in plain


def test_record_is_gone():
    """record produced nondeterministic screen capture; render replaces it."""
    result = runner.invoke(app, ["record", "--help"])
    assert result.exit_code != 0


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_render_writes_a_file(tmp_path):
    out = tmp_path / "out.mp4"
    result = runner.invoke(app, [
        "render", "examples/talk", "-o", str(out),
        "--fps", "5", "--size", "320x240", "--to", "10",
    ])
    assert result.exit_code == 0, result.stdout
    assert out.exists() and out.stat().st_size > 0


def test_a_bad_size_is_a_usage_error_for_render_and_export():
    for command in ("render", "export"):
        result = runner.invoke(app, [command, "examples/talk", "--size", "enormous"])
        assert result.exit_code == 2, (command, result.stdout)
        plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        assert "--size" in plain and "enormous" in plain, plain


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_render_writes_into_dist_by_default(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "index.html").write_text(
        '<!DOCTYPE html><html><head><link rel="stylesheet" href="/_auditorium/auditorium.css">'
        '<script type="module" src="/_auditorium/auditorium.js"></script></head><body>'
        '<main class="aud" data-format="explainer"><section data-beat="a" data-d="0.3"><p>x</p></section></main>'
        "</body></html>")
    result = runner.invoke(app, ["render", str(project), "--fps", "10", "--size", "320x180"])
    assert result.exit_code == 0, result.output
    assert (project / "dist" / "proj.mp4").stat().st_size > 0
