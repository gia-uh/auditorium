"""The ``auditorium`` command: ``run``, ``preview``, ``render``, ``export``, ``relay``.

Every command but ``relay`` takes a project: a folder holding index.html (or
the index.html itself). ``run`` and ``preview`` share ``_serve()`` and differ
only in which surface they open and whether shared navigation is on. SIGINT is
reset to ``SIG_DFL`` before uvicorn starts, for a clean shutdown.
"""
from __future__ import annotations

import asyncio
import json
import signal
from pathlib import Path

import typer
import uvicorn

from auditorium.console import console

app = typer.Typer(name="auditorium", help="Present, preview and render HTML decks, posters and videos")


def _version_callback(value: bool) -> None:
    if value:
        from importlib.metadata import version

        console.print(f"auditorium [bold]{version('auditorium')}[/]")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(False, "--version", callback=_version_callback, is_eager=True),
) -> None:
    """Present, preview and render HTML decks, posters and videos."""
    pass


def _project(path: Path) -> Path:
    """Resolve a project argument to its folder, or exit with what is missing."""
    path = path.resolve()
    folder = path.parent if path.is_file() and path.name == "index.html" else path
    if not (folder / "index.html").is_file():
        console.print(f"[red]Error:[/] {folder} has no index.html")
        raise typer.Exit(1)
    return folder


def _print_banner(
    folder: Path, host: str, port: int, presenter: bool = False, landing: str = "/"
) -> None:
    """Print a startup banner with the project and its URL."""
    from rich.panel import Panel
    from rich.text import Text

    body = Text()
    body.append("Project: ", style="dim")
    body.append(folder.name, style="bold")
    body.append("\n")
    body.append("URL:     ", style="dim")
    body.append(f"http://{host}:{port}{landing}", style="bold cyan")
    body.append("\n")
    body.append("Mode:    ", style="dim")
    if presenter:
        body.append("presenter (shared navigation)", style="yellow")
    else:
        body.append("independent (per-tab)", style="dim")

    console.print(Panel(body, title="[bold]Auditorium[/]", border_style="dim"))


@app.command()
def run(
    project: Path = typer.Argument(..., help="Project folder (or its index.html)"),
    host: str = typer.Option("127.0.0.1", help="Host to bind to"),
    port: int = typer.Option(8000, help="Port to bind to"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open browser automatically"),
    presenter: bool = typer.Option(False, "-p", "--presenter", help="Also open presenter view"),
    public: bool = typer.Option(False, "--public", help="Share via relay for remote viewers (not available yet, #104)"),
    relay_host: str = typer.Option("vps.apiad.net:4243", "--relay", help="Relay server host:port"),
    public_name: str = typer.Option(None, "--name", help="Custom name for the public URL (e.g. --name my-talk)"),
    watch: bool = typer.Option(True, "--watch/--no-watch", help="Watch the folder and hot-reload"),
) -> None:
    """Present a project live."""
    if public:
        # A relayed audience now needs the project's files, which the relay
        # does not carry yet. Refuse rather than hand out a URL that answers 501.
        console.print("[red]Error:[/] --public is not available yet: relaying a project folder lands with #104.")
        raise typer.Exit(1)
    _serve(
        _project(project), host, port, open_browser, watch,
        presenter=presenter, public=public, relay_host=relay_host,
        public_name=public_name,
    )


def _serve(
    folder: Path,
    host: str,
    port: int,
    open_browser: bool,
    watch: bool,
    *,
    presenter: bool = False,
    public: bool = False,
    relay_host: str = "",
    public_name: str | None = None,
    landing: str = "/",
) -> None:
    """Serve, and optionally open, a project.

    Shared by ``run`` and ``preview``: the two differ only in which surface
    they open and whether shared navigation is enabled, so the lifecycle is
    written once rather than kept in step by hand.
    """
    from auditorium.server import create_app

    application = create_app(folder, presenter_mode=presenter)
    _print_banner(folder, host, port, presenter, landing)

    if watch:
        _setup_watcher(application, folder)

    if public:
        _start_relay_bridge(relay_host, port, public_name)

    if open_browser:
        import threading
        import webbrowser

        def _open():
            import time
            time.sleep(0.5)
            webbrowser.open(f"http://{host}:{port}{landing}")
            if presenter:
                time.sleep(0.3)
                webbrowser.open(f"http://{host}:{port}/presenter")

        threading.Thread(target=_open, daemon=True).start()

    _start_live_status(application)

    signal.signal(signal.SIGINT, signal.SIG_DFL)
    uvicorn.run(application, host=host, port=port, log_level="warning")


@app.command()
def preview(
    project: Path = typer.Argument(..., help="Project folder (or its index.html)"),
    host: str = typer.Option("127.0.0.1", help="Host to bind to"),
    port: int = typer.Option(8000, help="Port to bind to"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open browser automatically"),
    watch: bool = typer.Option(True, "--watch/--no-watch", help="Watch the folder and hot-reload"),
) -> None:
    """Open the authoring preview: scrubber, frame stepping, loop-a-range."""
    _serve(_project(project), host, port, open_browser, watch, landing="/preview")


@app.command()
def render(
    project: Path = typer.Argument(..., help="Project folder (or its index.html)"),
    output: Path = typer.Option(Path("out.mp4"), "-o", "--output", help="Output file"),
    fps: int = typer.Option(30, "--fps", help="Frames per second"),
    size: str = typer.Option(None, "--size", help="WIDTHxHEIGHT or a preset: 1080p, 720p, vertical, square (default: the format's stage)"),
    fmt: str = typer.Option("mp4", "--format", help="mp4, webm, or png-sequence"),
    audio: Path | None = typer.Option(None, "--audio", help="Audio bed mixed into the render"),
    from_frame: int = typer.Option(0, "--from", help="First frame to render"),
    to_frame: int | None = typer.Option(None, "--to", help="Stop before this frame"),
) -> None:
    """Render a project to video by stepping frames deterministically."""
    from auditorium.render import parse_size, render_video

    folder = _project(project)
    dims = None
    if size is not None:
        try:
            dims = parse_size(size)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc

    asyncio.run(render_video(
        folder, output, fps=fps, size=dims, audio=audio, fmt=fmt,
        start_frame=from_frame, end_frame=to_frame,
    ))
    console.print(f"[green]✓[/] Rendered to [bold]{output}[/]")


@app.command()
def export(
    project: Path = typer.Argument(..., help="Project folder (or its index.html)"),
    fmt: str = typer.Option("png", "-f", "--format", help="Output format: png"),
    output: Path = typer.Option(None, "-o", "--output", help="Output folder (default: dist/)"),
    size: str = typer.Option(None, "--size", help="WIDTHxHEIGHT or a preset (default: the format's stage)"),
    steps: bool = typer.Option(False, "-s", "--steps", help="One image per press instead of per beat"),
) -> None:
    """Export each beat at its end state as a PNG."""
    from auditorium.render import parse_size

    folder = _project(project)
    if fmt != "png":
        # html and pdf come with bundle (#103); say so instead of guessing.
        console.print(f"[red]Error:[/] format [bold]'{fmt}'[/] is not available yet. Use png.")
        raise typer.Exit(1)
    dims = parse_size(size) if size else None
    from auditorium.exporter import export_png

    written = asyncio.run(export_png(folder, output or folder / "dist", size=dims, steps=steps))
    console.print(f"[green]✓[/] {len(written)} PNG files in [bold]{output or folder / 'dist'}/[/]")


def _start_live_status(application) -> None:
    """Start a background thread that displays live session status.

    Reports connections only. Per-client position used to be here, but the
    server no longer knows it: the browser holds the compiled timeline and
    seeks locally, so asking clients to report back would reintroduce exactly
    the chatter the timeline model removed.
    """
    import threading
    from rich.live import Live
    from rich.table import Table

    def _render():
        table = Table(show_header=True, header_style="dim", box=None, padding=(0, 1))
        table.add_column("Mode", style="dim", width=12)
        table.add_column("Connections", width=16)
        table.add_column("Presenter", width=14)

        if application.state.presenter_mode:
            pres = application.state.shared_pres
            n = len(pres.audience_clients)
            conns = f"{n} tab{'s' if n != 1 else ''}" if n else "[dim]none[/]"
            presenter = "[green]connected[/]" if pres.presenter_ws else "[dim]none[/]"
            table.add_row("shared", conns, presenter)
        else:
            n = len(application.state.sessions)
            conns = f"{n} tab{'s' if n != 1 else ''}" if n else "[dim]none[/]"
            table.add_row("independent", conns, "[dim]n/a[/]")

        return table

    def _run():
        import time
        time.sleep(1)
        with Live(_render(), console=console, refresh_per_second=2, transient=True) as live:
            while True:
                time.sleep(0.5)
                live.update(_render())

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


@app.command()
def relay(
    port: int = typer.Option(4243, help="Port to bind to"),
    host: str = typer.Option("0.0.0.0", help="Host to bind to"),
) -> None:
    """Run a relay server for public presentation sharing."""
    from auditorium.relay import create_relay_app

    relay_app = create_relay_app()
    console.print(f"[bold]Auditorium Relay[/] listening on [cyan]{host}:{port}[/]")
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    uvicorn.run(relay_app, host=host, port=port, log_level="warning")


def _start_relay_bridge(relay_host: str, local_port: int, name: str | None = None) -> None:
    """Connect to a relay server and bridge the local presentation to it."""
    import threading

    def _bridge():
        import time
        from websockets.sync.client import connect as ws_connect

        time.sleep(1.5)  # Wait for local server to start

        relay_protocol = "wss" if ":443" in relay_host else "ws"
        http_protocol = "https" if relay_protocol == "wss" else "http"

        try:
            # Connect to the relay as an upstream presenter
            relay_ws = ws_connect(f"{relay_protocol}://{relay_host}/upstream")

            # Send registration with optional custom name
            register_msg = {"type": "register"}
            if name:
                register_msg["name"] = name
            relay_ws.send(json.dumps(register_msg))

            reg = json.loads(relay_ws.recv())
            if reg.get("type") == "error":
                console.print(f"[red]Relay error:[/] {reg.get('message')}")
                return
            if reg.get("type") != "registered":
                console.print("[red]Relay error:[/] unexpected response")
                return

            session_id = reg["id"]
            public_url = f"{http_protocol}://{relay_host}/r/{session_id}/"
            console.print(f"\n[green]Public URL:[/] [bold cyan]{public_url}[/]\n")

            # Connect to the local server as an audience client
            local_ws = ws_connect(f"ws://127.0.0.1:{local_port}/ws")
            local_ws.send(json.dumps({"type": "hello", "slide": 0}))

            # Two threads: local→relay and relay→local
            def forward_local_to_relay():
                try:
                    while True:
                        data = local_ws.recv()
                        relay_ws.send(data)
                except Exception:
                    pass

            def forward_relay_to_local():
                try:
                    while True:
                        data = relay_ws.recv()
                        local_ws.send(data)
                except Exception:
                    pass

            t1 = threading.Thread(target=forward_local_to_relay, daemon=True)
            t2 = threading.Thread(target=forward_relay_to_local, daemon=True)
            t1.start()
            t2.start()
            t1.join()

        except Exception as e:
            console.print(f"[red]Relay error:[/] {e}")

    thread = threading.Thread(target=_bridge, daemon=True)
    thread.start()


def _setup_watcher(application, folder: Path) -> None:
    """Watch the project folder and tell every client to reload on a change.

    ``dist/`` is ignored: bundle, render and export write there, and a write
    that reloads the page it is capturing would never finish.
    """
    import threading

    from watchfiles import watch as watch_files

    dist = folder / "dist"

    def _filter(_change, path: str) -> bool:
        return not Path(path).is_relative_to(dist)

    def _watch():
        for _changes in watch_files(folder, watch_filter=_filter):
            console.print("[yellow]⟳[/] Change detected, reloading...")
            loop = getattr(application.state, "loop", None)
            if loop and loop.is_running():
                from auditorium.server import reload_project
                asyncio.run_coroutine_threadsafe(reload_project(application), loop)

    threading.Thread(target=_watch, daemon=True).start()
