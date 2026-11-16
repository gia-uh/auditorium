"""The ``audio-peak`` rule: the mix clipping, or music louder than the voice (#90).

It runs ``auditorium.mix``'s graph, the one ``render`` encodes, with taps on
the voice and music buses, so it measures what the video will carry after
laying, fading and ducking. ffmpeg reports the mix's peak; the two buses come
back as 8 kHz mono and are compared in windows of ``WINDOW`` seconds where the
voice speaks throughout. It runs with the layout pass, which already has the page's
published audio, and is skipped where ffmpeg is not installed.
"""
from __future__ import annotations

import math
import re
import shutil
import subprocess
import tempfile
from array import array
from pathlib import Path

from auditorium.check import Finding, finding
from auditorium.check.project import Project
from auditorium.mix import graph

WINDOW = 0.4      # seconds per loudness window
RATE = 8000       # Hz the buses are measured at
SPEAKING = 0.01   # RMS above which the voice counts as speaking, -40 dBFS
CLIPS_AT = -0.1   # dBFS: a peak this close to full scale clips once encoded
MONO = "aformat=sample_fmts=flt:sample_rates=8000:channel_layouts=mono"


def _db(x: float) -> float:
    return 20 * math.log10(max(x, 1e-10))


def _rms(path: Path, seconds: float = WINDOW) -> list[float]:
    samples = array("f")
    samples.frombytes(path.read_bytes())
    n = round(seconds * RATE)
    return [math.sqrt(sum(x * x for x in samples[i:i + n]) / len(samples[i:i + n]))
            for i in range(0, len(samples), n)]


def measure(folder: Path, clips: list[dict], duration: float) -> tuple[float, list[float], list[float]]:
    """(peak of the mix in dBFS, voice RMS per window, music RMS per window).

    A window's voice RMS is 0 unless the voice speaks through all of it, in
    each of its quarters: a window that catches a word's onset or tail would
    compare the music against a voice diluted by silence.
    """
    args, filters = graph(folder, clips, duration, taps=True)
    filters += f";[aout]volumedetect[peak];[voice_tap]{MONO}[v];[music_tap]{MONO}[m]"
    with tempfile.TemporaryDirectory(prefix="auditorium-audio-") as tmp:
        voice, music = Path(tmp) / "voice.f32", Path(tmp) / "music.f32"
        result = subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", *args, "-filter_complex", filters,
             "-map", "[peak]", "-f", "null", "-",
             "-map", "[v]", "-f", "f32le", str(voice), "-map", "[m]", "-f", "f32le", str(music)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg could not mix the audio (rc={result.returncode}):\n{result.stderr[-2000:]}")
        peak = re.search(r"max_volume: (-?[\d.]+|-inf) dB", result.stderr)
        top = float(peak.group(1)) if peak and peak.group(1) != "-inf" else -math.inf
        quarters = _rms(voice, WINDOW / 4)
        speaking = [min(quarters[i:i + 4]) > SPEAKING for i in range(0, len(quarters), 4)]
        return top, [v if s else 0.0 for v, s in zip(_rms(voice), speaking)], _rms(music)


def run(project: Project, clips: list[dict], duration: float) -> list[Finding]:
    if not clips or duration <= 0 or shutil.which("ffmpeg") is None:
        return []
    peak, voice, music = measure(project.folder, clips, duration)
    # The page publishes <audio> elements in document order, so the nth
    # non-voice clip is the nth <audio> in the source.
    elements = [e for e in project.source.elements if e.tag == "audio"]
    beds = [(c, e) for c, e in zip([c for c in clips if not c.get("voice")], elements)]
    out: list[Finding] = []

    def where(t: float | None) -> dict:
        if not beds:
            return {"line": None, "selector": None, "clip": None}
        sounding = [(c, e) for c, e in beds if t is None or c["t"] / 1000 <= t] or beds
        c, e = max(sounding, key=lambda ce: ce[0].get("gain", 1)) if t is None else sounding[-1]
        return {"line": e.line, "selector": f'audio[src="{c["src"]}"]', "clip": c}

    if peak > CLIPS_AT:
        at = where(None)
        clip = at["clip"]
        fix = (f'lower data-gain on <audio src="{clip["src"]}"> to {clip.get("gain", 1) * 10 ** ((-1 - peak) / 20):.2f}'
               if clip else "lower the narration clips' level before they go in assets/")
        out.append(finding("audio-peak", "index.html", at["line"],
                           f"the mix peaks at {peak:+.1f} dBFS; above {CLIPS_AT:g} dBFS it clips once encoded",
                           fix, selector=at["selector"]))

    loud = [(i * WINDOW, _db(m) - _db(v)) for i, (v, m) in enumerate(zip(voice, music)) if v > SPEAKING and m > v]
    if loud:
        t, t_end = loud[0][0], loud[-1][0] + WINDOW
        over = max(d for _, d in loud)
        at = where(t)
        clip = at["clip"]
        if clip is None:
            fix = "lower the music under the voice"
        elif not clip.get("duck"):
            fix = f'add data-duck to <audio src="{clip["src"]}">'
        else:
            fix = f'lower data-gain on <audio src="{clip["src"]}"> to {clip.get("gain", 1) * 10 ** ((-over - 6) / 20):.2f}'
        out.append(finding("audio-peak", "index.html", at["line"],
                           f"music is up to {over:.1f} dB louder than the voice in {len(loud)} windows "
                           f"of {WINDOW:g} s while it speaks",
                           fix, selector=at["selector"], t=round(t, 2), t_end=round(t_end, 2)))
    return out
