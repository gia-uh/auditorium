"""The ``auditorium`` command: ``template``, ``help``, ``check``, ``run``, ``preview``, ``render``, ``bundle``, ``export``, ``relay``.

Every command but ``template``, ``relay`` and ``help`` takes a project: a folder holding index.html (or
the index.html itself). ``run`` and ``preview`` share ``_serve()`` and differ
only in which surface they open and whether shared navigation is on. SIGINT is
reset to ``SIG_DFL`` before uvicorn starts, for a clean shutdown.
"""
from __future__ import annotations

import asyncio
import signal
import sys
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


def _size(value: str | None) -> tuple[int, int] | None:
    """Parse --size, or None for the format's stage; a bad value is a usage error."""
    if value is None:
        return None
    from auditorium.render import parse_size

    try:
        return parse_size(value)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--size") from exc


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
    public: bool = typer.Option(False, "--public", help="Share through a relay: remote viewers follow the presenter (implies --presenter)"),
    relay_host: str = typer.Option("vps.apiad.net:4243", "--relay", help="Relay server host:port"),
    public_name: str = typer.Option(None, "--name", help="Custom name for the public URL (e.g. --name my-talk)"),
    watch: bool = typer.Option(True, "--watch/--no-watch", help="Watch the folder and hot-reload"),
) -> None:
    """Present a project live."""
    _serve(
        _project(project), host, port, open_browser, watch,
        # A public audience only follows someone, and in shared mode the local
        # audience tab no longer navigates, so --public brings the presenter view.
        presenter=presenter or public, public=public, relay_host=relay_host,
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
        _start_relay_bridge(application, relay_host, port, public_name)

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
    output: Path = typer.Option(None, "-o", "--output", help="Output file (default: dist/NAME.mp4, or dist/frames/ for png-sequence)"),
    fps: int = typer.Option(30, "--fps", help="Frames per second"),
    size: str = typer.Option(None, "--size", help="WIDTHxHEIGHT or a preset: 1080p, 720p, vertical, square (default: the format's stage)"),
    fmt: str = typer.Option("mp4", "--format", help="mp4, webm, or png-sequence"),
    audio: Path | None = typer.Option(None, "--audio", help="Audio bed mixed into the render"),
    from_frame: int = typer.Option(0, "--from", help="First frame to render"),
    to_frame: int | None = typer.Option(None, "--to", help="Stop before this frame"),
) -> None:
    """Render a project to video by stepping frames deterministically."""
    from auditorium.render import render_video

    folder = _project(project)
    dims = _size(size)
    if output is None:
        output = folder / "dist" / ("frames" if fmt == "png-sequence" else f"{folder.name}.{fmt}")

    asyncio.run(render_video(
        folder, output, fps=fps, size=dims, audio=audio, fmt=fmt,
        start_frame=from_frame, end_frame=to_frame,
    ))
    console.print(f"[green]✓[/] Rendered to [bold]{output}[/]")


@app.command()
def bundle(
    project: Path = typer.Argument(..., help="Project folder (or its index.html)"),
    output: Path = typer.Option(None, "-o", "--output", help="Output file (default: dist/NAME.html)"),
    audio: bool = typer.Option(True, "--audio/--no-audio", help="Embed the audio, or leave it out"),
) -> None:
    """Write the project as one HTML file that presents from disk, with nothing to fetch."""
    _bundle(_project(project), output, audio)


def _bundle(folder: Path, output: Path | None, audio: bool) -> None:
    from auditorium.bundle import BundleError, bundle as write_bundle

    try:
        out = write_bundle(folder, output, audio=audio)
    except BundleError as exc:
        for problem in exc.problems:
            console.print(f"[red]error:[/] {problem}", highlight=False, soft_wrap=True)
        console.print(f"{len(exc.problems)} problems, nothing written")
        raise typer.Exit(1)
    kinds = ", ".join(f"{kind} {n / 1e6:.2f} MB" for kind, n in sorted(out.kinds.items()))
    console.print(f"[green]✓[/] [bold]{out.path}[/] ({kinds})", highlight=False, soft_wrap=True)
    console.print(f"{out.size} bytes in 1 file")


@app.command()
def export(
    project: Path = typer.Argument(..., help="Project folder (or its index.html)"),
    fmt: str = typer.Option("png", "-f", "--format", help="png, pdf or html (the same as bundle)"),
    output: Path = typer.Option(None, "-o", "--output", help="Output folder for png, file for pdf and html (default: dist/)"),
    size: str = typer.Option(None, "--size", help="png: WIDTHxHEIGHT or a preset (default: the format's stage)"),
    steps: bool = typer.Option(False, "-s", "--steps", help="png: one image per press instead of per beat"),
    beat: str = typer.Option(None, "-b", "--beat", help="png: only this beat, by id or number from 1"),
) -> None:
    """Export beats at their end state as PNG, the project as a PDF, or as one HTML file."""
    folder = _project(project)
    if fmt == "html":
        _bundle(folder, output, True)
        return
    if fmt == "pdf":
        from auditorium.exporter import export_pdf

        path = asyncio.run(export_pdf(folder, output or folder / "dist" / f"{folder.name}.pdf"))
        from pypdf import PdfReader

        console.print(f"[green]✓[/] [bold]{path}[/]", highlight=False, soft_wrap=True)
        console.print(f"{len(PdfReader(str(path)).pages)} pages")
        return
    if fmt != "png":
        console.print(f"[red]Error:[/] format [bold]'{fmt}'[/] is not one of png, pdf, html.")
        raise typer.Exit(1)
    dims = _size(size)
    from auditorium.exporter import export_png

    try:
        written = asyncio.run(export_png(folder, output or folder / "dist", size=dims, steps=steps, beat=beat))
    except ValueError as exc:
        console.print(f"[red]Error:[/] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]✓[/] {len(written)} PNG files in [bold]{output or folder / 'dist'}/[/]")


@app.command()
def check(
    project: Path = typer.Argument(..., help="Project folder (or its index.html)"),
    as_json: bool = typer.Option(False, "--json", help="Print every finding as JSON"),
) -> None:
    """Check a project against every rule; exit 1 on any error.

    Prints the first errors with their lines and fixes, then the counts, and
    writes every finding to dist/check.json. auditorium help check explains them.
    """
    import json

    from auditorium.check import check as run_check

    folder = _project(project)
    report = run_check(folder)
    data = report.as_dict()
    dist = folder / "dist"
    dist.mkdir(exist_ok=True)
    (dist / "check.json").write_text(json.dumps(data, indent=2) + "\n")
    # Plain print: messages quote the author's text, which may hold [brackets].
    print(json.dumps(data, indent=2) if as_json else report.text())
    if report.errors:
        raise typer.Exit(1)


template_app = typer.Typer(help="List, show and copy the templates a project starts from")
app.add_typer(template_app, name="template")


def _template_error(exc: Exception) -> None:
    print(f"error: {exc}", file=sys.stderr)
    raise typer.Exit(1)


@template_app.command("list")
def template_list(
    as_json: bool = typer.Option(False, "--json", help="Print the templates as JSON"),
) -> None:
    """List the templates, what each is for and the formats it makes."""
    import json

    from auditorium.templates import templates

    known = templates()
    if as_json:
        print(json.dumps([{"name": n, **m} for n, m in known.items()], indent=2))
        return
    width = max(len(n) for n in known)
    for name, meta in known.items():
        print(f"{name:<{width}}  {meta['summary']} ({', '.join(meta['formats'])})")
        print(f"{'':<{width}}  {meta['for']}")
    print(f"{len(known)} templates; auditorium template show NAME prints one")


@template_app.command("show")
def template_show(
    name: str = typer.Argument(..., help="Template to show"),
    as_json: bool = typer.Option(False, "--json", help="Print the template as JSON"),
) -> None:
    """Print a template: what it is for, its formats, and the index.html new copies."""
    import json

    from auditorium.templates import TemplateError, show

    try:
        shown = show(name)
    except TemplateError as exc:
        _template_error(exc)
    if as_json:
        print(json.dumps(shown, indent=2))
        return
    print(f"{name}: {shown['summary']}")
    print(shown["for"])
    print(f"formats: {', '.join(shown['formats'])} (the first is the default)")
    print(f"files: {', '.join(shown['files'])}, plus auditorium.toml and README.md")
    print()
    print(shown["index"], end="")
    print(f"{len(shown['files'])} files; auditorium template new {name} DIR")


@template_app.command("new")
def template_new(
    name: str = typer.Argument(..., help="Template to copy (auditorium template list)"),
    folder: Path = typer.Argument(..., help="New project folder; must not exist or be empty"),
    fmt: str = typer.Option(None, "--format", help="One of the template's formats (default: its first)"),
    theme: str = typer.Option(None, "--theme", help="A bundled theme to link, e.g. dark"),
    as_json: bool = typer.Option(False, "--json", help="Print what was written as JSON"),
) -> None:
    """Start a project from a template. The project owns its copy."""
    import json

    from auditorium.templates import TemplateError, new

    try:
        made = new(name, folder, fmt=fmt, theme=theme)
    except TemplateError as exc:
        _template_error(exc)
    if as_json:
        print(json.dumps(made, indent=2))
        return
    for rel in made["files"]:
        print(f"  {folder / rel}")
    print(f"{len(made['files'])} files written to {folder} from template {name}, format {made['format']}; "
          f"next: auditorium preview {folder}")


@app.command(name="help")
def help_(
    topic: str = typer.Argument(None, help="Topic to print; omit for the list"),
    name: str = typer.Argument(None, help="With topic 'rule': the rule to print"),
    all_: bool = typer.Option(False, "--all", help="Print every topic, in order"),
) -> None:
    """Print the guide that ships with this version, one topic at a time."""
    from auditorium.help import nearest, topic_path, topics

    if topic == "rule":
        _help_rule(name)
        return

    if all_ and topic is not None:
        print("error: --all prints every topic; give a topic or --all, not both.", file=sys.stderr)
        raise typer.Exit(1)
    if all_:
        known = topics()
        for name in known:
            print(topic_path(name).read_text())
        print(f"{len(known)} topics")
        return
    if topic is None:
        # Section 09: bare help shows start, the loop, then what else there is.
        known = topics()
        print(topic_path("start").read_text())
        width = max(len(n) for n in known)
        for name, summary in known.items():
            print(f"{name:<{width}}  {summary}")
        print(f"{len(known)} topics; auditorium help TOPIC prints one")
        return
    # Only a listed topic: the name becomes a path, and "../x" must not.
    if topic not in topics():
        guess = nearest(topic)
        hint = f" Did you mean '{guess}'?" if guess else ""
        print(f"error: no help topic '{topic}'.{hint} auditorium help lists them.", file=sys.stderr)
        raise typer.Exit(1)
    # Plain print, not the rich console: snippets hold [brackets] and markup
    # rich would eat, and an agent reads the bytes as written.
    print(topic_path(topic).read_text(), end="")


def _help_rule(name: str | None) -> None:
    """``help rule NAME``: one check rule, broken and fixed; bare, the list."""
    from auditorium.check import RULES
    from auditorium.help import rule_path

    if name is None:
        width = max(len(n) for n in RULES)
        for rule in RULES.values():
            print(f"{rule.name:<{width}}  {rule.group:<9}  {rule.catches}")
        print(f"{len(RULES)} rules; auditorium help rule NAME prints one")
        return
    if name not in RULES:
        import difflib

        guess = difflib.get_close_matches(name, list(RULES), n=1, cutoff=0.5)
        hint = f" Did you mean '{guess[0]}'?" if guess else ""
        print(f"error: no rule '{name}'.{hint} auditorium help rule lists them.", file=sys.stderr)
        raise typer.Exit(1)
    print(rule_path(name).read_text(), end="")


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


def _start_relay_bridge(application, relay_host: str, local_port: int, name: str | None = None) -> None:
    """Once the local server listens, bridge it to a relay and print the public URL."""
    import threading
    import time

    from auditorium.relay import bridge

    def _bridge():
        while getattr(application.state, "loop", None) is None:
            time.sleep(0.1)  # set by the app's startup hook
        try:
            url = bridge(relay_host, local_port, name)
        except Exception as e:
            console.print(f"[red]Relay error:[/] {e}")
            return
        console.print(f"\n[green]Public URL:[/] [bold cyan]{url}[/]\n")

    threading.Thread(target=_bridge, daemon=True).start()


def watch_filter(folder: Path):
    """Which changes in a project folder reload its pages.

    watchfiles' DefaultFilter (no .git, caches or editor swap files), and
    nothing under ``dist/``: bundle, render and export write there, and a write
    that reloads the page it is capturing would never finish.
    """
    from watchfiles import DefaultFilter

    default = DefaultFilter()
    dist = Path(folder).resolve() / "dist"

    def _filter(change, path: str) -> bool:
        return default(change, path) and not Path(path).resolve().is_relative_to(dist)

    return _filter


def _setup_watcher(application, folder: Path) -> None:
    """Watch the project folder and tell every client to reload on a change."""
    import threading

    from watchfiles import watch as watch_files

    def _watch():
        for _changes in watch_files(folder, watch_filter=watch_filter(folder)):
            console.print("[yellow]⟳[/] Change detected, reloading...")
            loop = getattr(application.state, "loop", None)
            if loop and loop.is_running():
                from auditorium.server import reload_project
                asyncio.run_coroutine_threadsafe(reload_project(application), loop)

    threading.Thread(target=_watch, daemon=True).start()
