"""State dataclasses for the Clip Extractor."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ClipPlaybackState:
    is_playing: bool = False
    current_frame: int = 0


@dataclass
class ClipSelectionState:
    in_point: Optional[int] = None
    out_point: Optional[int] = None

    @property
    def has_valid_selection(self) -> bool:
        return (self.in_point is not None and
                self.out_point is not None and
                self.out_point > self.in_point)

    def set_in(self, frame: int):
        self.in_point = frame
        if self.out_point is not None and self.out_point <= frame:
            self.out_point = None

    def set_out(self, frame: int):
        self.out_point = frame
        if self.in_point is not None and self.in_point >= frame:
            self.in_point = None

    def clear(self):
        self.in_point = None
        self.out_point = None


@dataclass
class ExportedClip:
    path: Path
    in_frame: int
    out_frame: int
    duration_seconds: float
    filename: str
