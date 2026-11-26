import re
import shutil

import pytest
from typer.testing import CliRunner

from auditorium.cli import app
from auditorium.render import CoverError, cover_seconds

runner = CliRunner()


def test_render_command_exists_and_documents_itself():
    result = runner.invoke(app, ["render", "--help"])
    assert result.exit_code == 0
    # Rich colours the help when it detects CI (GITHUB_ACTIONS is enough), and
    # the escape codes split "--fps" into "-" and "-fps". Match the plain text.
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
    for flag in ["--fps", "--size", "--format", "--audio", "--no-normalize",
                 "--max-size", "--target", "--cover", "--jobs"]:
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
        "--fps", "5", "--size", "320x180", "--to", "10",
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


def test_cover_seconds_reads_a_time_and_a_beat_end():
    published = {"duration": 5000, "beats": [
        {"id": "hook", "t": 1000, "d": 2000},
        {"id": "end", "t": 4000, "d": 1000},
    ]}
    assert cover_seconds(published, "1.5") == 1.5
    assert cover_seconds(published, "beat:hook") == 3.0
    assert cover_seconds(published, "99") == 5.0
    assert cover_seconds(published, "-2") == 0.0
    with pytest.raises(CoverError, match="no beat"):
        cover_seconds(published, "beat:nope")
    with pytest.raises(CoverError, match="SECONDS or beat"):
        cover_seconds(published, "soon")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_render_writes_a_cover_when_asked(tmp_path):
    out = tmp_path / "out.mp4"
    result = runner.invoke(app, [
        "render", "examples/talk", "-o", str(out),
        "--fps", "5", "--size", "320x180", "--to", "5", "--cover", "0.5",
    ])
    assert result.exit_code == 0, result.output
    cover = tmp_path / "out-cover.png"
    assert cover.exists() and cover.stat().st_size > 0
    from PIL import Image
    assert Image.open(cover).size == (320, 180)


def test_a_size_with_a_different_aspect_is_a_usage_error():
    result = runner.invoke(app, ["render", "examples/talk", "--size", "vertical", "--to", "1"])
    assert result.exit_code == 2, result.output
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    assert "--size" in plain and "aspect" in plain, plain
