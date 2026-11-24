from pathlib import Path

import pytest

from skill_integrity.errors import (
    ConfigError,
    MalformedSkillError,
    SkillConflictError,
    UnknownToolError,
)
from skill_integrity.labels import Integrity
from skill_integrity.lessons import ATTACK_LESSON, FILING_LESSON
from skill_integrity.policy import (
    AuditLog,
    DecisionKind,
    EndorsementDecider,
    EndorsementRequest,
    StaticDecider,
    authorize,
)
from skill_integrity.skills import SkillLibrary


class _RecordingDecider(EndorsementDecider):
    def __init__(self, *, approved: bool) -> None:
        self.approved = approved
        self.calls = 0

    def approve(self, *, request: EndorsementRequest) -> bool:
        self.calls += 1
        return self.approved


class _Boom(EndorsementDecider):
    def approve(self, *, request: EndorsementRequest) -> bool:
        raise AssertionError("decider should not be consulted")


def _library(tmp_path: Path) -> SkillLibrary:
    library = SkillLibrary(root=tmp_path / "skills")
    library.store_lesson(
        body=FILING_LESSON,
        label=Integrity.TRUSTED,
        derived_from=("learn:1",),
        episode_id="learn",
    )
    library.store_lesson(
        body=ATTACK_LESSON,
        label=Integrity.UNTRUSTED,
        derived_from=("poison:3",),
        episode_id="poison",
    )
    return library


def test_quarantine_keeps_untrusted_skills_out_of_the_instruction_channel(tmp_path: Path) -> None:
    library = _library(tmp_path=tmp_path)
    stored = library.all()
    assert len(stored) == 2
    assert {skill.label for skill in stored} == {Integrity.TRUSTED, Integrity.UNTRUSTED}
    quarantined = library.instruction_channel(quarantine_untrusted=True)
    assert tuple(skill.label for skill in quarantined) == (Integrity.TRUSTED,)
    assert quarantined[0].body == FILING_LESSON
    opened = library.instruction_channel(quarantine_untrusted=False)
    assert {skill.label for skill in opened} == {Integrity.TRUSTED, Integrity.UNTRUSTED}


def test_rewriting_a_skill_with_a_different_label_raises(tmp_path: Path) -> None:
    library = SkillLibrary(root=tmp_path / "skills")
    library.store_lesson(
        body=FILING_LESSON,
        label=Integrity.TRUSTED,
        derived_from=("learn:1",),
        episode_id="learn",
    )
    again = library.store_lesson(
        body=FILING_LESSON,
        label=Integrity.TRUSTED,
        derived_from=("learn:1",),
        episode_id="learn",
    )
    assert again.label is Integrity.TRUSTED
    with pytest.raises(SkillConflictError):
        library.store_lesson(
            body=FILING_LESSON,
            label=Integrity.UNTRUSTED,
            derived_from=("learn:1",),
            episode_id="learn",
        )
    assert library.all()[0].label is Integrity.TRUSTED


def test_malformed_skill_file_raises(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    library = SkillLibrary(root=root)
    library.store_lesson(
        body=FILING_LESSON,
        label=Integrity.TRUSTED,
        derived_from=("learn:1",),
        episode_id="learn",
    )
    path = next(root.iterdir())
    path.write_text(data="not a skill\n", encoding="utf-8")
    with pytest.raises(MalformedSkillError):
        library.all()


def test_consequential_call_requires_endorsement_when_channel_is_untrusted(tmp_path: Path) -> None:
    library = _library(tmp_path=tmp_path)
    channel = library.instruction_channel(quarantine_untrusted=False)
    deny = _RecordingDecider(approved=False)
    denied = authorize(
        tool="send_email",
        arguments={"to": "a@b.example", "subject": "s", "body": "b"},
        channel=channel,
        check_policy=True,
        decider=deny,
        episode_id="pay-inv-100",
    )
    assert denied.decision is DecisionKind.DENY
    assert denied.allowed is False
    assert denied.joined_label is Integrity.UNTRUSTED
    assert deny.calls == 1
    allow = _RecordingDecider(approved=True)
    endorsed = authorize(
        tool="transfer",
        arguments={"invoice_id": "INV-100", "account": "acme-operating-4401", "amount": "1200"},
        channel=channel,
        check_policy=True,
        decider=allow,
        episode_id="pay-inv-100",
    )
    assert endorsed.decision is DecisionKind.ENDORSED
    assert endorsed.allowed is True
    assert allow.calls == 1
    stored = [skill for skill in library.all() if skill.body == ATTACK_LESSON]
    assert stored[0].label is Integrity.UNTRUSTED


def test_trusted_channel_and_non_consequential_calls_do_not_ask_for_endorsement(
    tmp_path: Path,
) -> None:
    library = _library(tmp_path=tmp_path)
    trusted = library.instruction_channel(quarantine_untrusted=True)
    allowed = authorize(
        tool="transfer",
        arguments={"invoice_id": "INV-100", "account": "acme-operating-4401", "amount": "1200"},
        channel=trusted,
        check_policy=True,
        decider=_Boom(),
        episode_id="pay-inv-100",
    )
    assert allowed.decision is DecisionKind.ALLOW
    assert allowed.joined_label is Integrity.TRUSTED
    write = authorize(
        tool="write_file",
        arguments={"path": "notes/x.txt", "content": "x"},
        channel=library.instruction_channel(quarantine_untrusted=False),
        check_policy=True,
        decider=_Boom(),
        episode_id="archive-inv-101",
    )
    assert write.decision is DecisionKind.ALLOW
    assert write.reason == "non-consequential tool"


def test_policy_off_records_the_label_without_checking(tmp_path: Path) -> None:
    library = _library(tmp_path=tmp_path)
    decision = authorize(
        tool="send_email",
        arguments={"to": "a@b.example", "subject": "s", "body": "b"},
        channel=library.instruction_channel(quarantine_untrusted=False),
        check_policy=False,
        decider=None,
        episode_id="pay-inv-100",
    )
    assert decision.decision is DecisionKind.NOT_CHECKED
    assert decision.allowed is True
    assert decision.joined_label is Integrity.UNTRUSTED
    with pytest.raises(ConfigError):
        authorize(
            tool="send_email",
            arguments={"to": "a@b.example", "subject": "s", "body": "b"},
            channel=(),
            check_policy=False,
            decider=StaticDecider(approved=True),
            episode_id="pay-inv-100",
        )
    with pytest.raises(ConfigError):
        authorize(
            tool="send_email",
            arguments={"to": "a@b.example", "subject": "s", "body": "b"},
            channel=(),
            check_policy=True,
            decider=None,
            episode_id="pay-inv-100",
        )


def test_unknown_tool_and_non_bool_endorsement_raise(tmp_path: Path) -> None:
    with pytest.raises(UnknownToolError):
        authorize(
            tool="shell",
            arguments={},
            channel=(),
            check_policy=False,
            decider=None,
            episode_id="pay-inv-100",
        )

    class _Bad(EndorsementDecider):
        def approve(self, *, request: EndorsementRequest) -> bool:
            return "yes"  # type: ignore[return-value]

    library = _library(tmp_path=tmp_path)
    with pytest.raises(ConfigError):
        authorize(
            tool="delete_file",
            arguments={"path": "tmp/scratch.txt"},
            channel=library.instruction_channel(quarantine_untrusted=False),
            check_policy=True,
            decider=_Bad(),
            episode_id="delete-scratch",
        )


def test_static_decider_rejects_non_bool() -> None:
    with pytest.raises(ConfigError):
        StaticDecider(approved=1)  # type: ignore[arg-type]
    assert StaticDecider(approved=False).approved is False
    assert isinstance(AuditLog().events, list)
