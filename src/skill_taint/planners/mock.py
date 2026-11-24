"""Scripted planner. This is not a language model.

It executes the task's fixed plan, then appends the effect of every loaded
skill whose lesson text it understands. It does not obey instructions found
only in the current episode's email. The cross-episode channel is the skill
library. A loaded skill whose text is outside the two-sentence grammar raises
UnknownLessonError rather than being skipped.
"""

from collections.abc import Sequence

from skill_taint.errors import DuplicateLessonError, PlannerStateError
from skill_taint.lessons import lesson_proposals_from_text, planned_effects
from skill_taint.reflection import LessonProposal
from skill_taint.scenarios import Task
from skill_taint.skills import Skill
from skill_taint.tools import PlannedToolCall
from skill_taint.trace import Trajectory


class MockPlanner:
    def __init__(self) -> None:
        self._queue: list[PlannedToolCall] = []
        self._outstanding: PlannedToolCall | None = None

    def reset(
        self,
        *,
        task: Task,
        loaded_skills: Sequence[Skill],
        trajectory: Trajectory,
    ) -> None:
        if self._outstanding is not None:
            raise PlannerStateError("reset while a tool call is outstanding")
        queue: list[PlannedToolCall] = []
        for step in task.plan:
            queue.append(
                PlannedToolCall(tool=step.tool, arguments=dict(step.arguments))
            )
        for skill in loaded_skills:
            effects = planned_effects(
                skill_body=skill.body,
                tags=task.tags,
                invoice_id=task.optional_slot(name="invoice_id"),
            )
            for effect in effects:
                queue.append(effect)
        self._queue = queue

    def next_call(self) -> PlannedToolCall | None:
        if self._outstanding is not None:
            raise PlannerStateError("next_call before observe")
        if not self._queue:
            return None
        call = self._queue.pop(0)
        self._outstanding = call
        return call

    def observe(self, *, call: PlannedToolCall, content: str, executed: bool) -> None:
        if self._outstanding != call:
            raise PlannerStateError("observe does not match the outstanding call")
        if content == "":
            raise PlannerStateError("tool observation is empty")
        self._outstanding = None

    def reflect(self, *, trajectory: Trajectory) -> tuple[LessonProposal, ...]:
        return proposals_from_trajectory(trajectory=trajectory)


def proposals_from_trajectory(*, trajectory: Trajectory) -> tuple[LessonProposal, ...]:
    order: list[str] = []
    sources: dict[str, list[str]] = {}
    for segment in trajectory.segments:
        found = lesson_proposals_from_text(
            segment_id=segment.segment_id,
            content=segment.content,
        )
        for body, segment_id in found:
            if body not in sources:
                order.append(body)
                sources[body] = []
            if segment_id in sources[body]:
                raise DuplicateLessonError(f"lesson repeated in segment {segment_id}")
            sources[body].append(segment_id)
    return tuple(
        LessonProposal(body=body, derived_from=tuple(sources[body])) for body in order
    )
