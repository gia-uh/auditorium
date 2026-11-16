"""Write and read audio files: WAV, FLAC, MP3 and OGG."""

from __future__ import annotations

from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from auditorium._vendor.euterpe.sound.core import RATE

# extension -> (soundfile format, subtype); None lets soundfile pick its default
FORMATS = {
    ".wav": ("WAV", "PCM_24"),
    ".flac": ("FLAC", "PCM_24"),
    ".mp3": ("MP3", None),
    ".ogg": ("OGG", "VORBIS"),
}

# libsndfile's default MP3 is about 85 kbps and cuts everything above 17.5 kHz;
# constant 264 kbps keeps the spectrum up to 20.5 kHz; from compression level 0.3 up the
# encoder also lowers the level, by 0.18 dB at 0.3 and 0.45 dB at 0.5
_MP3 = {"bitrate_mode": "CONSTANT", "compression_level": 0.2}


def write(samples: np.ndarray, path: str | Path, *, rate: int = RATE) -> Path:
    """Write samples rendered at 48 kHz to path, in the format its extension names.

    Samples beyond ±1 are clipped. With another rate the samples are resampled first.
    Missing parent directories are created. Returns the path.
    """
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in FORMATS:
        raise ValueError(f"cannot write {path.name}: supported extensions are {', '.join(sorted(FORMATS))}")
    x = np.clip(np.asarray(samples, np.float32), -1.0, 1.0)
    if rate != RATE:
        g = gcd(rate, RATE)
        x = np.clip(resample_poly(x, rate // g, RATE // g, axis=0), -1.0, 1.0).astype(np.float32)
    path.parent.mkdir(parents=True, exist_ok=True)
    fmt, subtype = FORMATS[ext]
    sf.write(path, x, rate, format=fmt, subtype=subtype, **(_MP3 if ext == ".mp3" else {}))
    return path


def read(path: str | Path) -> tuple[np.ndarray, int]:
    """Read an audio file as float32 samples, (n,) or (n, channels), and its sample rate."""
    samples, rate = sf.read(path, dtype="float32")
    return samples, rate
