"""The audio mix: every clip a page publishes, laid, faded and ducked (#73, #90).

``render`` encodes this graph beside the frames, and the ``audio-peak`` rule
runs the same graph to measure it, so what the check hears is what the video
carries.

A clip is ``{src, t (ms), gain, duck, loop, voice}`` as ``auditorium.js``
publishes it: narration clips have ``voice``; ``<audio>`` elements have the
rest.

- **Lay**: an ``<audio loop>`` repeats from its time to the end of the video.
- **Fade**: a looped clip fades in over ``FADE_IN``; every clip but the voice
  fades out over the video's last ``FADE_OUT`` seconds, so a bed never stops
  dead on the last frame. Fades are placed on the whole video's clock, so a
  ranged render (``--from``/``--to``) cuts the same samples a full one has.
- **Duck**: ``<audio data-duck>`` clips are summed and pressed down by a
  sidechain compressor keyed on the voice, so music drops while a narrator
  speaks and comes back after. With no voice, ``data-duck`` does nothing.

Every chain is converted to one format first: ``amix`` and
``sidechaincompress`` need matching rates and layouts.
"""
from __future__ import annotations

from pathlib import Path

FADE_IN = 1.0   # seconds, at the start of a looped clip
FADE_OUT = 2.0  # seconds, at the end of the video
FORMAT = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
# About 12 dB off the music while the voice speaks; back within half a second.
DUCK = "sidechaincompress=threshold=0.02:ratio=8:attack=20:release=400"


def _sum(labels: list[str], out: str) -> str:
    if len(labels) == 1:
        return f"[{labels[0]}]anull[{out}]"
    inputs = "".join(f"[{label}]" for label in labels)
    return f"{inputs}amix=inputs={len(labels)}:normalize=0:dropout_transition=0[{out}]"


def graph(project: Path, clips: list[dict], duration: float, offset: float = 0.0,
          first: int = 0, taps: bool = False) -> tuple[list[str], str]:
    """ffmpeg input arguments and a filter graph that mixes ``clips`` into ``[aout]``.

    ``duration`` is the whole video's length in seconds and ``offset`` where a
    ranged render starts. Inputs are numbered from ``first`` (the frames are
    input 0 in a render). With ``taps`` the graph also outputs the voice bus as
    ``[voice_tap]`` and the music after ducking as ``[music_tap]``, for the check.
    """
    span = max(duration - offset, 0.001)  # seconds of output
    args: list[str] = []
    chains: list[str] = []
    voices: list[str] = []
    ducked: list[str] = []
    others: list[str] = []
    for i, c in enumerate(clips):
        if c.get("loop"):
            args += ["-stream_loop", "-1"]
        args += ["-i", str(project / c["src"])]
        start = c.get("t", 0) / 1000
        left = max(duration - start, 0.001)  # seconds the clip can sound in the video
        steps = [FORMAT]
        if c.get("loop"):
            steps += [f"atrim=duration={left:.3f}", f"afade=t=in:d={FADE_IN}"]
        if not c.get("voice") and left > FADE_OUT:
            steps.append(f"afade=t=out:st={left - FADE_OUT:.3f}:d={FADE_OUT}")
        at = start - offset
        if at < 0:
            steps += [f"atrim=start={-at:.3f}", "asetpts=PTS-STARTPTS"]
        steps += [f"adelay={max(0, round(at * 1000))}:all=1", f"volume={c.get('gain', 1)}"]
        label = f"a{i}"
        chains.append(f"[{first + i}:a]{','.join(steps)}[{label}]")
        (voices if c.get("voice") else ducked if c.get("duck") else others).append(label)

    buses: list[str] = []
    if voices:
        chains.append(_sum(voices, "voice"))
        if ducked:
            # The key is padded to the video's length, so a voice that ends
            # before the music does not end the compressor's output with it.
            chains.append("[voice]asplit=2[voice_mix][voice_key]")
            chains.append(f"[voice_key]apad=whole_dur={span:.3f}[voice_keyp]")
            chains.append(_sum(ducked, "duck_in"))
            chains.append(f"[duck_in][voice_keyp]{DUCK}[ducked]")
            others = ["ducked", *others]
            voices = ["voice_mix"]
        else:
            voices = ["voice"]
    else:
        others = [*ducked, *others]
    if others:
        chains.append(_sum(others, "music"))
    for bus, present in (("voice", voices), ("music", others)):
        if not present:
            continue
        name = voices[0] if bus == "voice" else "music"
        if taps:
            chains.append(f"[{name}]asplit=2[{bus}_out][{bus}_tap]")
            name = f"{bus}_out"
        buses.append(name)
    if taps:
        # The check reads both buses; a missing one is silence.
        for bus, present in (("voice", voices), ("music", others)):
            if not present:
                chains.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={span:.3f}[{bus}_tap]")
    chains.append(_sum(buses, "mixed"))
    # Padded, then trimmed, to the video's length: a mix that ends early (the
    # last narration clip before the last beat ends, no looping bed) would
    # otherwise end the video with it under render's -shortest.
    chains.append(f"[mixed]apad=whole_dur={span:.3f},atrim=duration={span:.3f}[aout]")
    return args, ";".join(chains)
