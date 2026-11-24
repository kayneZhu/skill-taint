import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from skill_integrity.agent import AgentConfig, run_episode
from skill_integrity.errors import InvalidArgumentError, MissingConfigError, UnexpectedModelOutputError
from skill_integrity.labels import Integrity
from skill_integrity.lessons import ATTACK_LESSON
from skill_integrity.llm import (
    ChatTransport,
    OpenAIPlanner,
    chat_completions_url,
    parse_lessons,
    parse_model_turn,
)
from skill_integrity.policy import AuditLog, DecisionKind, StaticDecider
from skill_integrity.reflection import Granularity
from skill_integrity.scenarios import Task, fresh_workspace
from skill_integrity.skills import SkillLibrary
from skill_integrity.workspace import Effects


class _ScriptedTransport(ChatTransport):
    def __init__(self, *, responses: tuple[dict[str, object], ...]) -> None:
        self._responses = list(responses)
        self.bodies: list[dict[str, object]] = []

    def post_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        body: Mapping[str, object],
        timeout_seconds: float,
    ) -> dict[str, object]:
        del url, headers, timeout_seconds
        self.bodies.append(dict(body))
        if not self._responses:
            raise AssertionError("unexpected HTTP call")
        return self._responses.pop(0)


def _tool_response(*, name: str, arguments: dict[str, str]) -> dict[str, object]:
    return {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments),
                            },
                        }
                    ],
                },
            }
        ]
    }


def _stop_response(*, content: str) -> dict[str, object]:
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content, "tool_calls": None},
            }
        ]
    }


def _probe() -> Task:
    return Task(
        task_id="probe",
        user_instruction="file this note as status reviewed only",
        tags=frozenset({"probe"}),
        slots=(),
        plan=(),
        expect=Effects(sends=(), transfers=(), writes=(), deletes=()),
    )


def test_missing_key_and_bad_base_url_raise_before_any_request() -> None:
    class _Exploding(ChatTransport):
        def post_json(self, *, url: str, headers, body, timeout_seconds: float):
            raise AssertionError("transport was called")

    with pytest.raises(MissingConfigError) as caught:
        OpenAIPlanner(
            api_key="",
            base_url="https://example.invalid/v1",
            model="test-model",
            transport=_Exploding(),
        )
    assert "OPENAI_API_KEY" in caught.value.missing
    with pytest.raises(MissingConfigError):
        chat_completions_url(base_url="example.invalid/v1")
    assert (
        chat_completions_url(base_url="https://example.invalid/v1/")
        == "https://example.invalid/v1/chat/completions"
    )


def test_parser_rejects_ambiguous_tool_payloads() -> None:
    with pytest.raises(UnexpectedModelOutputError):
        parse_model_turn(
            payload={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "a",
                                    "type": "function",
                                    "function": {
                                        "name": "read_email",
                                        "arguments": json.dumps({"email_id": "poison-1"}),
                                    },
                                },
                                {
                                    "id": "b",
                                    "type": "function",
                                    "function": {
                                        "name": "read_email",
                                        "arguments": json.dumps({"email_id": "poison-1"}),
                                    },
                                },
                            ],
                        },
                    }
                ]
            }
        )
    with pytest.raises(InvalidArgumentError):
        parse_model_turn(
            payload=_tool_response(
                name="send_email",
                arguments={"to": "a@b.example", "subject": "s", "body": "b", "note": "x"},
            )
        )
    with pytest.raises(UnexpectedModelOutputError):
        parse_lessons(content='```json\n{"lessons":[]}\n```')
    assert parse_lessons(content='\n{"lessons":[]}\n') == ()


def test_untrusted_skill_in_the_prompt_denies_a_consequential_call(tmp_path: Path) -> None:
    library = SkillLibrary(root=tmp_path / "skills")
    library.store_lesson(
        body=ATTACK_LESSON,
        label=Integrity.UNTRUSTED,
        derived_from=("seed:0",),
        episode_id="seed",
    )
    transport = _ScriptedTransport(
        responses=(
            _tool_response(
                name="transfer",
                arguments={
                    "invoice_id": "INV-100",
                    "account": "acme-operating-4401",
                    "amount": "1200",
                },
            ),
            _stop_response(content="done"),
            _stop_response(content='{"lessons":[]}'),
        )
    )
    planner = OpenAIPlanner(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model="test-model",
        transport=transport,
    )
    audit = AuditLog()
    workspace = fresh_workspace()
    run_episode(
        config=AgentConfig(
            quarantine_untrusted=False,
            check_policy=True,
            granularity=Granularity.SEGMENT,
            decider=StaticDecider(approved=False),
        ),
        planner=planner,
        library=library,
        workspace=workspace,
        audit=audit,
        task=_probe(),
    )
    assert workspace.effects_for(episode_id="probe").transfers == ()
    denied = [event for event in audit.events if event.tool == "transfer"]
    assert len(denied) == 1
    assert denied[0].decision is DecisionKind.DENY
    assert denied[0].joined_label is Integrity.UNTRUSTED
    user_message = transport.bodies[0]["messages"][1]["content"]
    assert ATTACK_LESSON in user_message
    assert "test-key" not in json.dumps(transport.bodies[0])


def test_quarantine_omits_the_untrusted_skill_and_a_trusted_citation_stays_trusted(
    tmp_path: Path,
) -> None:
    library = SkillLibrary(root=tmp_path / "skills")
    library.store_lesson(
        body=ATTACK_LESSON,
        label=Integrity.UNTRUSTED,
        derived_from=("seed:0",),
        episode_id="seed",
    )
    lesson = {
        "body": "file this note as status reviewed only",
        "derived_from": ["probe:1"],
    }
    transport = _ScriptedTransport(
        responses=(
            _tool_response(name="read_email", arguments={"email_id": "mail-util"}),
            _stop_response(content="done"),
            _stop_response(content=json.dumps({"lessons": [lesson]})),
        )
    )
    planner = OpenAIPlanner(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model="test-model",
        transport=transport,
    )
    result = run_episode(
        config=AgentConfig(
            quarantine_untrusted=True,
            check_policy=True,
            granularity=Granularity.SEGMENT,
            decider=StaticDecider(approved=False),
        ),
        planner=planner,
        library=library,
        workspace=fresh_workspace(),
        audit=AuditLog(),
        task=_probe(),
    )
    user_message = transport.bodies[0]["messages"][1]["content"]
    assert ATTACK_LESSON not in user_message
    assert result.loaded_skill_ids == ()
    stored = [skill for skill in result.lessons if skill.body == lesson["body"]]
    assert len(stored) == 1
    assert stored[0].label is Integrity.TRUSTED
    assert stored[0].derived_from == ("probe:1",)
