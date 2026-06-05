"""A :class:`Filmstrip` — an ordered list of ``(frame, hold_ms)`` + serializers.

A *filmstrip* is the simulation's intermediate form: a sequence of rendered ANSI
frames, each with a hold duration. It serializes three ways:

* :meth:`Filmstrip.cast` — an asciinema v2 ``.cast`` (the replayable video);
* :meth:`Filmstrip.storyboard_txt` — SGR-stripped frames with labels (review/diff);
* :meth:`Filmstrip.storyboard_ansi` — full-fidelity ANSI frames with labels
  (``less -R`` to scrub through).

Every frame is produced by one of colleague's *pure* render functions, so the
whole filmstrip is deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

from .cast import strip_sgr, to_cast

#: ``(body, hold_ms)``.
FrameT = Tuple[str, int]

#: Cast geometry. Wide enough for the session status line ("· engine … · model …
#: · local"), tall enough for a grown conversation panel.
DEFAULT_WIDTH = 100
_MIN_HEIGHT = 24


@dataclass
class Filmstrip:
    """An ordered list of rendered frames plus serializers to cast / storyboard."""

    name: str
    title: str
    frames: List[FrameT] = field(default_factory=list)
    width: int = DEFAULT_WIDTH

    def add(self, body: str, hold_ms: int) -> "Filmstrip":
        """Append one frame; returns ``self`` for chaining."""
        self.frames.append((body, int(hold_ms)))
        return self

    def extend(self, frames: List[FrameT]) -> "Filmstrip":
        """Append a list of frames (used to stitch sub-flows into one ride)."""
        self.frames.extend((b, int(h)) for b, h in frames)
        return self

    @property
    def height(self) -> int:
        """Tallest frame's line count (+1 slack), clamped to a sane minimum."""
        tallest = max((body.count("\n") + 1 for body, _ in self.frames), default=1)
        return max(_MIN_HEIGHT, tallest + 1)

    @property
    def duration_ms(self) -> int:
        return sum(hold for _, hold in self.frames)

    def cast(self) -> str:
        return to_cast(self.frames, width=self.width, height=self.height, title=self.title)

    def storyboard_txt(self) -> str:
        return self._storyboard(strip=True)

    def storyboard_ansi(self) -> str:
        return self._storyboard(strip=False)

    def _storyboard(self, *, strip: bool) -> str:
        out: List[str] = [
            f"# {self.title}",
            f"# {len(self.frames)} frames · {self.duration_ms}ms",
            "",
        ]
        for i, (body, hold) in enumerate(self.frames, 1):
            out.append(f"────────── frame {i}/{len(self.frames)} · {hold}ms ──────────")
            out.append(strip_sgr(body) if strip else body)
            out.append("")
        return "\n".join(out) + "\n"
