"""The renderer: a score played on its parts' instruments, as one unit."""

from __future__ import annotations

from typing import TYPE_CHECKING

from auditorium._vendor.euterpe.instruments.core import play
from auditorium._vendor.euterpe.score.perform import Performance, part_seeds
from auditorium._vendor.euterpe.sound.core import Mix

if TYPE_CHECKING:
    from auditorium._vendor.euterpe.instruments.core import Note
    from auditorium._vendor.euterpe.score.model import Score


class ScoreAudio(Mix):
    """One Phrase per part, each times its part's gain, summed: stereo if any part is, a mono part then on both sides
    equally. The spectrum is the sum of the parts' spectra, each scaled by its gain. parts holds the phrases by name and
    notes every part's notes in time order. Pan, effects and buses are a later layer's, and so is a console's output
    stage: a chip's channel plays like any instrument."""

    def __init__(self, score: Score, seed: int = 0, performance: Performance | None = None):
        if not score.parts:
            raise ValueError("Score: it has no parts, so there is nothing to play")
        for part in score.parts.values():
            if part.instrument is None:
                raise ValueError(f"part {part.name!r} has no instrument, so it cannot play")
        self.score = score
        self.seed = seed
        self.performance = performance or score.performance
        notes = self.performance.notes(score, seed)
        seeds = part_seeds(seed, len(score.parts))
        self.parts = {name: play(part.instrument, notes[name], play_seed)
                      for (name, part), (_, play_seed) in zip(score.parts.items(), seeds)}
        super().__init__(*self.parts.values(), gains=[part.gain for part in score.parts.values()])

    @property
    def notes(self) -> list[Note]:
        """Every part's notes, in time order."""
        return sorted((note for phrase in self.parts.values() for note in phrase.notes), key=lambda note: note.time)

    def take(self, seconds: float | None = None, caption: str | None = None):
        """Render into a Clip, captioned for its view. Without seconds: the whole duration, tails included, however
        long, so a piece is never cut at MAX_DEFAULT."""
        return super().take(self.duration if seconds is None else seconds, caption)
