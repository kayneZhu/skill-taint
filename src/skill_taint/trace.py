"""Labeled trajectory segments. Reflection cites these ids."""

from dataclasses import dataclass, field

from skill_taint.errors import ConfigError, DuplicateSegmentError, UnknownSegmentError
from skill_taint.labels import Integrity


@dataclass(frozen=True, kw_only=True)
class Segment:
    segment_id: str
    role: str
    content: str
    label: Integrity
    source: str


@dataclass(kw_only=True)
class Trajectory:
    segments: list[Segment] = field(default_factory=list)

    def add(self, *, segment: Segment) -> None:
        for existing in self.segments:
            if existing.segment_id == segment.segment_id:
                raise DuplicateSegmentError(f"duplicate segment id {segment.segment_id}")
        self.segments.append(segment)

    def get(self, *, segment_id: str) -> Segment:
        for segment in self.segments:
            if segment.segment_id == segment_id:
                return segment
        raise UnknownSegmentError(f"unknown segment id {segment_id}")


class SegmentIds:
    def __init__(self, *, episode_id: str) -> None:
        if episode_id == "":
            raise ConfigError("episode_id is empty")
        self._episode_id = episode_id
        self._n = 0

    def next(self) -> str:
        segment_id = f"{self._episode_id}:{self._n}"
        self._n += 1
        return segment_id
