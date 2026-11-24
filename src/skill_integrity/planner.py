"""Planner interface. Implementations do not assign integrity labels."""

from collections.abc import Sequence
from typing import Protocol

from skill_integrity.reflection import LessonProposal
from skill_integrity.scenarios import Task
from skill_integrity.skills import Skill
from skill_integrity.tools import PlannedToolCall
from skill_integrity.trace import Trajectory


class EpisodePlanner(Protocol):
    def reset(
        self,
        *,
        task: Task,
        loaded_skills: Sequence[Skill],
        trajectory: Trajectory,
    ) -> None:
        """Start one episode. loaded_skills is the instruction channel."""

    def next_call(self) -> PlannedToolCall | None:
        """Return the next tool call, or None when the episode's actions are done."""

    def observe(self, *, call: PlannedToolCall, content: str, executed: bool) -> None:
        """Receive the tool result or the denial text for the outstanding call."""

    def reflect(self, *, trajectory: Trajectory) -> tuple[LessonProposal, ...]:
        """Propose lessons. The runtime assigns labels and may reject them."""
