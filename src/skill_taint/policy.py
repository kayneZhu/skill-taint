"""Tool-call endorsement gate.

The monitored control dependence of a call is the whole instruction channel:
the trusted user task plus every skill the loader actually placed in the
prompt. The planner does not get to declare a smaller dependence. If that
join is untrusted, a consequential tool runs only when the decider endorses
that specific call. Endorsement does not change the skill's stored label.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum

from skill_taint.errors import ConfigError, UnknownToolError
from skill_taint.labels import Integrity, join_all
from skill_taint.skills import Skill
from skill_taint.tools import ALL_TOOLS, CONSEQUENTIAL_TOOLS


class DecisionKind(Enum):
    ALLOW = "allow"
    DENY = "deny"
    ENDORSED = "endorsed"
    NOT_CHECKED = "not_checked"


@dataclass(frozen=True, kw_only=True)
class EndorsementRequest:
    episode_id: str
    tool: str
    arguments: Mapping[str, str]
    channel_label: Integrity
    channel_skill_ids: tuple[str, ...]


class EndorsementDecider:
    """Structural stand-in. Subclasses must override approve."""

    def approve(self, *, request: EndorsementRequest) -> bool:
        raise ConfigError("EndorsementDecider.approve is not implemented")


@dataclass(frozen=True, kw_only=True)
class StaticDecider(EndorsementDecider):
    """CLI stand-in: the same answer for every request. Default use is deny."""

    approved: bool

    def __post_init__(self) -> None:
        if not isinstance(self.approved, bool):
            raise ConfigError("approved must be a bool")

    def approve(self, *, request: EndorsementRequest) -> bool:
        return self.approved


@dataclass(frozen=True, kw_only=True)
class Authorization:
    allowed: bool
    decision: DecisionKind
    reason: str
    joined_label: Integrity
    channel_skill_ids: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class AuditEvent:
    episode_id: str
    step_index: int
    tool: str
    arguments: Mapping[str, str]
    channel_skill_ids: tuple[str, ...]
    joined_label: Integrity
    decision: DecisionKind
    reason: str


@dataclass(kw_only=True)
class AuditLog:
    events: list[AuditEvent] = field(default_factory=list)

    def record(self, *, event: AuditEvent) -> None:
        self.events.append(event)


def channel_label(*, skills: Sequence[Skill]) -> Integrity:
    labels = [Integrity.TRUSTED]
    for skill in skills:
        labels.append(skill.label)
    return join_all(labels=labels)


def authorize(
    *,
    tool: str,
    arguments: Mapping[str, str],
    channel: Sequence[Skill],
    check_policy: bool,
    decider: EndorsementDecider | None,
    episode_id: str,
) -> Authorization:
    if tool not in ALL_TOOLS:
        raise UnknownToolError(f"unknown tool: {tool}")
    if check_policy and decider is None:
        raise ConfigError("policy checks require an endorsement decider")
    if not check_policy and decider is not None:
        raise ConfigError("endorsement decider is set but policy checks are off")
    label = channel_label(skills=channel)
    skill_ids = tuple(skill.skill_id for skill in channel)
    if not check_policy:
        return Authorization(
            allowed=True,
            decision=DecisionKind.NOT_CHECKED,
            reason="policy checks are off",
            joined_label=label,
            channel_skill_ids=skill_ids,
        )
    if tool not in CONSEQUENTIAL_TOOLS:
        return Authorization(
            allowed=True,
            decision=DecisionKind.ALLOW,
            reason="non-consequential tool",
            joined_label=label,
            channel_skill_ids=skill_ids,
        )
    if label is Integrity.TRUSTED:
        return Authorization(
            allowed=True,
            decision=DecisionKind.ALLOW,
            reason="instruction channel is trusted",
            joined_label=label,
            channel_skill_ids=skill_ids,
        )
    if label is not Integrity.UNTRUSTED:
        raise ConfigError(f"unexpected channel label {label}")
    if decider is None:
        raise ConfigError("policy checks require an endorsement decider")
    request = EndorsementRequest(
        episode_id=episode_id,
        tool=tool,
        arguments=arguments,
        channel_label=label,
        channel_skill_ids=skill_ids,
    )
    approved = decider.approve(request=request)
    if not isinstance(approved, bool):
        raise ConfigError("endorsement decider must return a bool")
    if approved:
        return Authorization(
            allowed=True,
            decision=DecisionKind.ENDORSED,
            reason="human endorsement for this call",
            joined_label=label,
            channel_skill_ids=skill_ids,
        )
    return Authorization(
        allowed=False,
        decision=DecisionKind.DENY,
        reason="untrusted instruction channel; endorsement denied",
        joined_label=label,
        channel_skill_ids=skill_ids,
    )
