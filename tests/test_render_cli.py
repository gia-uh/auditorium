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


def test_run_public_refuses_until_the_relay_carries_a_project():
    """The relay viewer answers 501 until #104; --public must say so and exit
    non-zero rather than print a URL that does not work."""
    result = runner.invoke(app, ["run", "examples/talk", "--public", "--no-open"])
    assert result.exit_code == 1
    assert "#104" in result.stdout
