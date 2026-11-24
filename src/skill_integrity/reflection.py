"""Assign an integrity label to a reflection proposal.

The reflector does not choose the label. Segment mode joins the cited
segments after checking that the body occurs verbatim in one of them.
Episode mode joins every segment in the trajectory. A citation cannot
upgrade a lesson whose text never appears, and a citation of only a trusted
segment cannot launder a body that is not in that segment.
"""

from dataclasses import dataclass

from skill_integrity.errors import MalformedLessonError, UngroundedLessonError
from skill_integrity.labels import Integrity, join_all
from skill_integrity.trace import Trajectory


class Granularity:
    SEGMENT = "segment"
    EPISODE = "episode"


@dataclass(frozen=True, kw_only=True)
class LessonProposal:
    body: str
    derived_from: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class LabeledLesson:
    body: str
    label: Integrity
    derived_from: tuple[str, ...]


def assign_label(
    *,
    proposal: LessonProposal,
    trajectory: Trajectory,
    granularity: str,
) -> LabeledLesson:
    if proposal.body == "" or proposal.body.strip() != proposal.body or "\n" in proposal.body:
        raise MalformedLessonError("lesson body must be a single non-empty line")
    if not proposal.derived_from:
        raise MalformedLessonError("lesson citation is empty")
    if len(set(proposal.derived_from)) != len(proposal.derived_from):
        raise MalformedLessonError("lesson citation repeats a segment id")
    cited = tuple(
        trajectory.get(segment_id=segment_id) for segment_id in proposal.derived_from
    )
    if granularity == Granularity.SEGMENT:
        if not any(proposal.body in segment.content for segment in cited):
            raise UngroundedLessonError(
                "lesson body is not a substring of the cited segments: "
                + ", ".join(proposal.derived_from)
            )
        return LabeledLesson(
            body=proposal.body,
            label=join_all(labels=tuple(segment.label for segment in cited)),
            derived_from=proposal.derived_from,
        )
    if granularity == Granularity.EPISODE:
        if not any(proposal.body in segment.content for segment in trajectory.segments):
            raise UngroundedLessonError(
                "lesson body does not occur in the trajectory"
            )
        return LabeledLesson(
            body=proposal.body,
            label=join_all(labels=tuple(segment.label for segment in trajectory.segments)),
            derived_from=tuple(segment.segment_id for segment in trajectory.segments),
        )
    raise MalformedLessonError(f"unknown label granularity: {granularity}")


def reject_duplicate_bodies(*, proposals: tuple[LessonProposal, ...]) -> None:
    seen: set[str] = set()
    for proposal in proposals:
        if proposal.body in seen:
            raise MalformedLessonError("duplicate lesson body in one reflection")
        seen.add(proposal.body)


def render_transcript(*, trajectory: Trajectory) -> str:
    blocks = [
        (
            f"[segment {segment.segment_id} label={segment.label} source={segment.source}]\n"
            f"{segment.content}"
        )
        for segment in trajectory.segments
    ]
    return "\n\n".join(blocks)
