"""The structure pass: rules that read the files and start no browser.

Each rule is a function from a Project to findings, registered in ``STRUCTURE``
in the order the spec lists them. They are cheap, so all of them run even when
one fires; only the next pass waits for zero errors.
"""
from __future__ import annotations

import difflib
import re
from collections.abc import Iterator

from auditorium.check import Finding, finding
from auditorium import narration
from auditorium.check import vocab
from auditorium.check.project import Project, is_external, strip_css_comments, strip_js_comments


def _nearest(name: str, choices) -> str | None:
    m = difflib.get_close_matches(name, list(choices), n=1, cutoff=0.4)
    return m[0] if m else None


def parse(p: Project) -> Iterator[Finding]:
    for line, message, fix in p.source.problems:
        yield finding("parse", "index.html", line, message, fix)
    if p.main is None:
        yield finding("parse", "index.html", 1, 'no <main class="aud">: the runtime builds nothing',
                      'put the beats inside <main class="aud" data-format="deck"> in <body>')


def unknown_name(p: Project) -> Iterator[Finding]:
    main = p.main
    if main is not None and main.get("data-format") is not None and main.get("data-format") not in vocab.formats():
        bad = main.get("data-format")
        yield _unknown(main, "data-format", bad, vocab.formats(), "format")
    own = _author_classes(p)
    for el in p.source.elements:
        for attr, names, what in (("data-enter", vocab.entrances(), "entrance"),
                                  ("data-exit", vocab.entrances(), "exit"),
                                  ("data-idle", vocab.idles(), "idle"),
                                  ("data-layer", vocab.layers(), "layer")):
            value = el.get(attr)
            if value is not None and value not in names:
                yield _unknown(el, attr, value, names, what)
        # data-grade takes several names at once: "tint vignette".
        for attr, names, what in (("data-emphasis", vocab.emphases(), "emphasis"),
                                  ("data-ambient", vocab.ambients(), "ambient"),
                                  ("data-grade", vocab.grades(), "grade")):
            for value in (el.get(attr) or "").split():
                if value not in names:
                    yield _unknown(el, attr, value, names, what)
        if el.tag == "section" and el.parent is main:
            for cls in el.classes:
                if cls not in vocab.layouts() and cls not in own:
                    guess = _nearest(cls, vocab.layouts())
                    fix = (f'set class="{guess}"' if guess else
                           f"use one of the layouts ({', '.join(vocab.layouts())}), or define .{cls} in theme.css")
                    yield finding("unknown-name", "index.html", el.line,
                                  f'class="{cls}" on a beat is not a layout and no author CSS defines it', fix,
                                  selector=el.selector())


def _unknown(el, attr, value, names, what) -> Finding:
    guess = _nearest(value, names)
    fix = f'set {attr}="{guess}"' if guess else f"use one of: {', '.join(names)}"
    return finding("unknown-name", "index.html", el.line, f'{attr}="{value}" is not a {what}', fix,
                   selector=el.selector())


def _author_classes(p: Project) -> set[str]:
    out: set[str] = set()
    for code in p.css:
        out |= set(re.findall(r"\.(-?[_a-zA-Z][\w-]*)", strip_css_comments(code.text)))
    return out


def external_url(p: Project) -> Iterator[Finding]:
    allowed = set(p.endpoints)
    for ref in [*p.refs, *p.js_urls]:
        if is_external(ref.url) and ref.url not in allowed:
            yield finding(
                "external-url", ref.file, ref.line,
                f"{ref.url} loads from the network; an artifact must work offline",
                "download it into assets/ and point to that path, or, for live data, declare it under "
                "[data] in auditorium.toml with a fixture",
                selector=ref.element.selector() if ref.element else None)


def missing_asset(p: Project) -> Iterator[Finding]:
    root = p.folder.resolve()
    for ref in p.refs:
        if is_external(ref.url):
            continue
        path = p.resolve(ref)
        if path is None:
            continue
        runtime = ref.url.startswith("/_auditorium/")
        if not runtime and not path.resolve().is_relative_to(root):
            yield finding("missing-asset", ref.file, ref.line,
                          f"{ref.url} is outside the project folder, so a bundle cannot carry it",
                          "copy the file into assets/ and point to assets/NAME",
                          selector=ref.element.selector() if ref.element else None)
        elif not path.is_file():
            near = _near_file(p, path)
            fix = ("it is an entry in assets.yaml: run auditorium assets" if not runtime and _in_manifest(p, path)
                   else f'point to "{near}"' if near else
                   f"add the file at {path.relative_to(root).as_posix() if not runtime else ref.url}, "
                   "or remove the reference")
            yield finding("missing-asset", ref.file, ref.line, f"{ref.url} is not in the project", fix,
                          selector=ref.element.selector() if ref.element else None)
    for url, fixture in p.endpoints.items():
        if not fixture.is_file():
            yield finding("missing-asset", "auditorium.toml", None,
                          f"the fixture for {url} is not in the project",
                          "add the JSON file the [data] entry names as fixture")


def _in_manifest(p: Project, path) -> bool:
    from auditorium.assets import ManifestError, load

    try:
        keys = {e.key for e in load(p.folder)}
    except ManifestError:
        return False
    return path.resolve().relative_to(p.folder.resolve()).as_posix() in keys


def _near_file(p: Project, path) -> str | None:
    root = p.folder.resolve()
    files = [f.relative_to(root).as_posix() for f in root.rglob("*")
             if f.is_file() and "dist" not in f.relative_to(root).parts]
    try:
        want = path.resolve().relative_to(root).as_posix()
    except ValueError:
        return None
    m = difflib.get_close_matches(want, files, n=1, cutoff=0.6)
    return m[0] if m else None


_WALL = re.compile(r"\b(requestAnimationFrame|setInterval|setTimeout|Date\.now|performance\.now|Math\.random)\b")
_WALL_FIX = {
    "Math.random": "use auditorium.rng(seed)() for a random number that is the same on every run",
}


def wall_clock(p: Project) -> Iterator[Finding]:
    for code in p.js:
        for m in _WALL.finditer(strip_js_comments(code.text)):
            name = m.group(1)
            yield finding(
                "wall-clock", code.file, code.line_at(m.start()),
                f"{name} runs on the wall clock, so a render and a seek cannot reproduce it",
                _WALL_FIX.get(name, "move the code into auditorium.track(t => ...), "
                                    "a function of the time t in seconds"))


_TRANSITION = re.compile(r"(?<![\w-])transition(?:-[a-z-]+)?\s*:")


def bare_transition(p: Project) -> Iterator[Finding]:
    for code in p.css:
        for m in _TRANSITION.finditer(strip_css_comments(code.text)):
            yield finding(
                "bare-transition", code.file, code.line_at(m.start()),
                "a CSS transition finishes on its own, and a seek backwards past it does nothing (D3)",
                "delete the transition and animate with data-enter or data-exit on the element")


def _num(el, attr) -> float | None:
    v = el.get(attr)
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def time_attrs(p: Project) -> Iterator[Finding]:
    timed = vocab.formats().get(p.format)
    for section in p.sections:
        # A narrated beat without data-d takes its length from the clip.
        if timed and not section.has("data-d") and not section.has("data-say"):
            yield finding("time-attrs", "index.html", section.line,
                          f"a {p.format} plays on a clock, and this beat has no length",
                          'add data-d="N" to the <section>: its length in seconds',
                          selector=section.selector(), beat=section.get("data-beat"))
    for el in p.source.find("audio"):
        # The runtime publishes the <audio> of each beat; one outside every
        # beat is never played, and render mixes nothing for it.
        if not any(a.tag == "section" and a.has("data-beat") for a in el.ancestors()):
            yield finding("time-attrs", "index.html", el.line,
                          f'<audio src="{el.get("src", "")}"> is outside every beat: it never plays, and the video is silent',
                          "move it into the first beat, <section data-beat>; with loop it plays to the end of the video",
                          selector=el.selector())
    for el in p.source.elements:
        for attr in ("data-d", "data-in", "data-out", "data-dur", "data-step"):
            if el.get(attr) is not None and _num(el, attr) is None:
                yield finding("time-attrs", "index.html", el.line,
                              f'{attr}="{el.get(attr)}" is not a number of seconds',
                              f'write {attr} as a number, such as {attr}="1.5"', selector=el.selector())
        t_in, t_out = _num(el, "data-in"), _num(el, "data-out")
        if t_in is not None and t_out is not None and t_in >= t_out:
            yield finding("time-attrs", "index.html", el.line,
                          f"data-in={t_in:g} is not before data-out={t_out:g}",
                          "make data-out later than data-in, or swap them", selector=el.selector())
        if el.has("data-cue") and el.has("data-in"):
            yield finding("time-attrs", "index.html", el.line,
                          "data-cue and data-in both set when the element enters",
                          "keep one: data-cue for narration, data-in for a time", selector=el.selector())


def duration(p: Project) -> Iterator[Finding]:
    """A timed format outside its length, or a poster with more beats than one."""
    b = vocab.bounds().get(p.format, {})
    if "seconds" in b and p.main is not None:
        lengths = [_length(p, s) for s in p.sections]
        if None not in lengths:  # a missing or bad data-d is time-attrs' finding
            low, high = b["seconds"]
            total = sum(lengths)
            if not low <= total <= high:
                want = f"add beats or lengthen them by {low - total:g} s" if total < low else \
                    f"cut beats or shorten them by {total - high:g} s"
                yield finding("duration", "index.html", p.main.line,
                              f"the beats sum to {total:g} s; a {p.format} lasts {low:g} to {high:g} s",
                              f"{want} (the data-d of each <section>)", selector=p.main.selector())
    if "beats" in b and len(p.sections) > b["beats"]:
        extra = p.sections[b["beats"]]
        yield finding("duration", "index.html", extra.line,
                      f"a {p.format} is one image, and this is beat {b['beats'] + 1} of {len(p.sections)}",
                      'keep one <section>, or use data-format="deck" for slides',
                      selector=extra.selector(), beat=extra.get("data-beat"))


def _length(p: Project, section) -> float | None:
    """A beat's data-d, or the length its narration clip gives it."""
    if section.has("data-d") or not section.has("data-say"):
        return _num(section, "data-d")
    try:
        return narration.beat_seconds(narration.load(p.folder, section.get("data-say")))
    except (OSError, narration.NarrationError):
        return None


def _narrations(p: Project):
    """(section, Narration or None, problem or None) for each beat with data-say.
    A missing alignment file is missing-asset's finding, so it has no problem."""
    for section in p.sections:
        value = section.get("data-say")
        if not value:
            continue
        try:
            yield section, narration.load(p.folder, value), None
        except FileNotFoundError:
            yield section, None, None
        except (OSError, narration.NarrationError) as e:
            yield section, None, str(e)


def overrun(p: Project) -> Iterator[Finding]:
    """A clip that leaves less than MARGIN seconds of its beat after the voice."""
    for section, n, _ in _narrations(p):
        if n is None or not (p.folder / n.clip).is_file():
            continue
        d = _num(section, "data-d")
        if d is None:
            continue  # the clip sets the length
        clip = narration.clip_seconds(p.folder, n)
        if narration.LEAD + clip > d - narration.MARGIN:
            need = round(narration.LEAD + clip + narration.TAIL, 2)
            yield finding("overrun", "index.html", section.line,
                          f"{n.clip} lasts {clip:.2f} s and starts at {narration.LEAD:g} s, "
                          f"so it ends {narration.LEAD + clip - d:+.2f} s from the end of a {d:g} s beat; "
                          f"leave at least {narration.MARGIN:g} s",
                          f'set data-d="{need:g}", or delete data-d so the clip sets the length',
                          selector=section.selector(), beat=section.get("data-beat"))


def cue_missing(p: Project) -> Iterator[Finding]:
    """A data-cue phrase that its beat's narration never says, or a cue with no narration."""
    said = {id(s): (n, problem) for s, n, problem in _narrations(p)}
    for section, (n, problem) in ((s, said[id(s)]) for s in p.sections if id(s) in said):
        if problem:
            yield finding("cue-missing", "index.html", section.line, problem,
                          "regenerate the alignment with character or word times, as the TTS "
                          "service or aligner writes it", selector=section.selector(),
                          beat=section.get("data-beat"))
        elif n is not None and not (p.folder / n.clip).is_file():
            yield finding("missing-asset", "index.html", section.line,
                          f"{n.clip}, the clip of {n.alignment}, is not in the project",
                          f'add the clip at {n.clip}, or name it with "audio" in {n.alignment}',
                          selector=section.selector(), beat=section.get("data-beat"))
    for el in p.source.elements:
        phrase = el.get("data-cue")
        if phrase is None:
            continue
        beat = next((a for a in el.ancestors() if a.tag == "section"), None)
        n, problem = said.get(id(beat), (None, None)) if beat is not None else (None, None)
        if beat is None or not beat.has("data-say"):
            yield finding("cue-missing", "index.html", el.line,
                          f'data-cue="{phrase}" waits for a phrase, and its beat has no narration',
                          'add data-say="assets/vo/NAME.json" to the <section>, or use data-in="N"',
                          selector=el.selector())
        elif n is not None and n.cue(phrase) is None:
            yield finding("cue-missing", "index.html", el.line,
                          f'"{phrase}" is not said in {n.alignment}',
                          "copy the phrase as the narration says it, or regenerate the clip "
                          "from a script that says it", selector=el.selector(),
                          beat=beat.get("data-beat"))


def duplicate_id(p: Project) -> Iterator[Finding]:
    seen: dict[str, int] = {}
    for el in p.source.elements:
        i = el.get("id")
        if not i:
            continue
        if i in seen:
            yield finding("duplicate-id", "index.html", el.line,
                          f'id="{i}" is already used at line {seen[i]}; anchors and findings pick one at random',
                          f'rename this one, e.g. id="{i}-2"', selector=el.selector())
        else:
            seen[i] = el.line


STRUCTURE = [parse, unknown_name, external_url, missing_asset, wall_clock, bare_transition,
             time_attrs, duration, duplicate_id, overrun, cue_missing]


def run(p: Project) -> list[Finding]:
    return [f for rule in STRUCTURE for f in rule(p)]


def placeholders(p: Project) -> list[Finding]:
    """The placeholder and placeholder-asset rules. Reported with the layout pass, where the spec puts
    it: it needs no browser, but a fresh template is all placeholders, and its
    structure should be judged first."""
    out = []
    for el in p.source.elements:
        if el.has("data-placeholder"):
            text = " ".join(el.text.split())[:40]
            out.append(finding("placeholder", "index.html", el.line,
                               f'"{text}" is template text to replace' if text else
                               "a template placeholder is still here",
                               "write the real content, then delete data-placeholder",
                               selector=el.selector()))
    for ref in p.refs:
        if "placeholder" in ref.url.rsplit("/", 1)[-1].lower():
            out.append(finding("placeholder", ref.file, ref.line, f"{ref.url} is a template placeholder asset",
                               "put the real file in assets/ and point to it",
                               selector=ref.element.selector() if ref.element else None))
    out += _placeholder_assets(p)
    return out


def _placeholder_assets(p: Project) -> Iterator[Finding]:
    """References to an assets.yaml entry that nothing has resolved: its key
    holds a labelled placeholder, or nothing yet."""
    from auditorium.assets import unresolved

    pending = unresolved(p.folder)
    root = p.folder.resolve()
    for ref in p.refs:
        path = None if is_external(ref.url) else p.resolve(ref)
        if path is None or not path.resolve().is_relative_to(root):
            continue
        key = path.resolve().relative_to(root).as_posix()
        if key in pending:
            entry = pending[key]
            fix = {"file": f"put the file at {entry.spec.get('file')}, or fix that path in assets.yaml, "
                           "then run auditorium assets",
                   "capture": "run auditorium assets, and if the capture fails, fix its URL or state",
                   "generate": "run auditorium assets with an image provider, or replace the entry with "
                               "file: and a real image"}[entry.kind]
            yield finding("placeholder-asset", ref.file, ref.line,
                          f"{ref.url} is the {entry.kind} entry in assets.yaml, not resolved yet",
                          fix, selector=ref.element.selector() if ref.element else None)
