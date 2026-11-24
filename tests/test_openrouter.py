import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from skill_taint.agent import run_research_episode
from skill_taint.errors import IncompleteModelCall, MissingConfigError
from skill_taint.labels import Integrity
from skill_taint.lessons import FILING_LESSON
from skill_taint.llm import ChatTransport
from skill_taint.planners.openrouter import (
    OPENROUTER_URL,
    CostLedger,
    OpenRouterPlanner,
    build_request,
    cost_from_usage,
    load_openrouter_key,
    parse_skill_bodies,
)
from skill_taint.skills import SkillLibrary
from skill_taint.workspaces.invoice import campaign_task_by_id, campaign_workspace


class _ScriptedTransport(ChatTransport):
    def __init__(self, *, responses: tuple[dict[str, object] | Exception, ...]) -> None:
        self._responses = list(responses)
        self.bodies: list[dict[str, object]] = []
        self.headers: list[dict[str, str]] = []
        self.urls: list[str] = []

    def post_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        body: Mapping[str, object],
        timeout_seconds: float,
    ) -> dict[str, object]:
        del timeout_seconds
        self.urls.append(url)
        self.headers.append({key: value for key, value in headers.items()})
        self.bodies.append(dict(body))
        if not self._responses:
            raise AssertionError("unexpected HTTP call")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _usage(*, cost: float | None, prompt: int = 100, completion: int = 50) -> dict[str, object]:
    usage: dict[str, object] = {
        "completion_tokens": completion,
        "completion_tokens_details": {"reasoning_tokens": 40},
        "prompt_tokens": prompt,
    }
    if cost is not None:
        usage["cost"] = cost
    return usage


def _stop(*, content: str, model: str, cost: float | None = 0.01) -> dict[str, object]:
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": content, "role": "assistant"},
            }
        ],
        "model": model,
        "provider": "TestProvider",
        "usage": _usage(cost=cost),
    }


def _length(*, model: str) -> dict[str, object]:
    return {
        "choices": [
            {
                "finish_reason": "length",
                "message": {"content": "", "role": "assistant"},
            }
        ],
        "model": model,
        "provider": "TestProvider",
        "usage": _usage(cost=0.002, completion=1000),
    }


def _planner(
    *,
    model: str,
    transport: _ScriptedTransport,
    tmp_path: Path,
    api_key: str = "test-key",
) -> OpenRouterPlanner:
    return OpenRouterPlanner(
        api_key=api_key,
        model=model,
        transport=transport,
        ledger=CostLedger(path=tmp_path / "ledger.json", stop_usd=9.0),
        campaign_id="unit",
        planning_max_tokens=1000,
        reflection_max_tokens=1400,
        raw_path=tmp_path / "raw.jsonl",
    )


def test_missing_key_raises_before_transport(tmp_path: Path) -> None:
    transport = _ScriptedTransport(responses=())
    with pytest.raises(MissingConfigError) as caught:
        OpenRouterPlanner(
            api_key="",
            model="deepseek/deepseek-v4.1-flash-1017",
            transport=transport,
            ledger=CostLedger(path=tmp_path / "ledger.json"),
            campaign_id="unit",
            planning_max_tokens=1000,
            reflection_max_tokens=1400,
        )
    assert "OPENROUTER_API_KEY" in caught.value.missing
    assert transport.bodies == []


def test_request_omits_temperature_for_opus_and_disables_fallbacks() -> None:
    opus = build_request(
        model="anthropic/claude-opus-5.5",
        messages=({"role": "user", "content": "hi"},),
        max_tokens=1000,
        temperature=None,
        include_tools=True,
    )
    deepseek = build_request(
        model="deepseek/deepseek-v4.1-flash-1017",
        messages=({"role": "user", "content": "hi"},),
        max_tokens=1400,
        temperature=0,
        include_tools=False,
    )
    assert "temperature" not in opus
    assert "models" not in opus
    assert opus["reasoning"] == {"effort": "high"}
    assert opus["provider"] == {"allow_fallbacks": False}
    assert deepseek["temperature"] == 0
    assert "tools" not in deepseek
    assert "models" not in deepseek
    cost, source = cost_from_usage(
        request_model="deepseek/deepseek-v4.1-flash-1017",
        usage={"completion_tokens": 1000, "prompt_tokens": 1_000_000},
    )
    assert source == "catalog"
    assert cost == pytest.approx(expected=0.03 + 0.0002)
    priced, priced_source = cost_from_usage(
        request_model="deepseek/deepseek-v4.1-flash-1017",
        usage={"completion_tokens": 1, "cost": 0.25, "prompt_tokens": 1},
    )
    assert priced_source == "usage.cost"
    assert priced == 0.25


def test_retry_once_then_incomplete_and_ledger_keeps_both_charges(tmp_path: Path) -> None:
    model = "deepseek/deepseek-v4.1-flash-1017"
    transport = _ScriptedTransport(responses=(_length(model=model), _length(model=model)))
    planner = _planner(model=model, transport=transport, tmp_path=tmp_path)
    planner.reset(
        task=campaign_task_by_id(task_id="e0-learn"),
        loaded_skills=(),
        spotlight=False,
    )
    with pytest.raises(IncompleteModelCall) as caught:
        planner.next_call()
    assert "empty content" in caught.value.reason
    assert len(transport.bodies) == 2
    assert transport.urls == [OPENROUTER_URL, OPENROUTER_URL]
    assert planner._ledger.spent_usd == pytest.approx(expected=0.004)
    reloaded = CostLedger(path=tmp_path / "ledger.json", stop_usd=9.0)
    assert reloaded.spent_usd == pytest.approx(expected=0.004)
    assert reloaded.can_start_campaign() is True
    raw = (tmp_path / "raw.jsonl").read_text(encoding="utf-8")
    assert "test-key" not in raw
    assert "Bearer" not in raw
    for body in transport.bodies:
        encoded = json.dumps(body)
        assert "test-key" not in encoded
        assert "models" not in body
    assert all(header["Authorization"] == "Bearer test-key" for header in transport.headers)


def test_reflection_accepts_one_fence_and_records_provider(tmp_path: Path) -> None:
    model = "google/gemini-4-hydrogen"
    fenced = '```json\n{"skills": [{"body": "File invoices under invoices/."}]}\n```'
    transport = _ScriptedTransport(responses=(_stop(content=fenced, model=model, cost=0.1),))
    planner = _planner(model=model, transport=transport, tmp_path=tmp_path)
    bodies = planner.reflect(
        transcript="[segment e0-learn:0 role=user label=trusted source=user_task]\nFile it.",
        partition="trusted",
        spotlight=True,
    )
    assert bodies == ("File invoices under invoices/.",)
    body = transport.bodies[0]
    assert body["temperature"] == 0
    assert body["max_tokens"] == 1400
    assert body["reasoning"] == {"effort": "high"}
    assert "tools" not in body
    assert planner.usage_records[0]["provider"] == "TestProvider"
    assert planner.usage_records[0]["returned_model"] == model
    assert planner.usage_records[0]["reasoning_tokens"] == 40
    assert parse_skill_bodies(content='\n{"skills": []}\n') == ()
    system = body["messages"][0]["content"]
    assert "<<UNTRUSTED_DATA>>" in system


def _tool(*, name: str, arguments: dict[str, str], model: str) -> dict[str, object]:
    return {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": None,
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "function": {"arguments": json.dumps(arguments), "name": name},
                            "id": "call-1",
                            "type": "function",
                        }
                    ],
                },
            }
        ],
        "model": model,
        "provider": "TestProvider",
        "usage": _usage(cost=0.001),
    }


def test_off_episode_stores_the_reflection_and_sends_no_fallback_field(tmp_path: Path) -> None:
    model = "deepseek/deepseek-v4.1-flash-1017"
    transport = _ScriptedTransport(
        responses=(
            _tool(name="read_email", arguments={"email_id": "mail-util"}, model=model),
            _stop(content="done", model=model, cost=0.001),
            _stop(
                content=json.dumps({"skills": [{"body": FILING_LESSON}]}),
                model=model,
                cost=0.002,
            ),
        )
    )
    planner = _planner(model=model, transport=transport, tmp_path=tmp_path)
    result = run_research_episode(
        condition="off",
        planner=planner,
        library=SkillLibrary(root=tmp_path / "skills"),
        workspace=campaign_workspace(phrasing="explicit"),
        task=campaign_task_by_id(task_id="e0-learn"),
    )
    assert result.lessons[0].body == FILING_LESSON
    assert result.lessons[0].label is Integrity.TRUSTED
    assert result.effects.sends == ()
    assert len(transport.bodies) == 3
    assert all("models" not in body for body in transport.bodies)
    assert all(body["provider"] == {"allow_fallbacks": False} for body in transport.bodies)
    tool_message = transport.bodies[1]["messages"][3]
    assert tool_message["role"] == "tool"
    assert "Filing exercise" in tool_message["content"]
    assert "test-key" not in json.dumps(transport.bodies)


def test_missing_usage_is_priced_from_the_generation_record(tmp_path: Path) -> None:
    model = "anthropic/claude-opus-5.5"

    class _Lookup(OpenRouterPlanner):
        def _fetch_generation(self, *, generation_id: str) -> dict[str, object]:
            assert generation_id == "gen-test"
            return {
                "data": {
                    "native_tokens_reasoning": 1,
                    "tokens_completion": 4,
                    "tokens_prompt": 3,
                    "total_cost": 0.2,
                }
            }

    transport = _ScriptedTransport(
        responses=(
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "done", "role": "assistant"},
                    }
                ],
                "id": "gen-test",
                "model": model,
                "provider": "Anthropic",
            },
        )
    )
    planner = _Lookup(
        api_key="test-key",
        model=model,
        transport=transport,
        ledger=CostLedger(path=tmp_path / "ledger.json", stop_usd=9.0),
        campaign_id="unit",
        planning_max_tokens=1000,
        reflection_max_tokens=1400,
    )
    planner.reset(
        task=campaign_task_by_id(task_id="e4-utility"),
        loaded_skills=(),
        spotlight=False,
    )
    assert planner.next_call() is None
    assert planner._ledger.spent_usd == pytest.approx(expected=0.2)
    assert planner._ledger.can_start_campaign() is True
    assert "temperature" not in transport.bodies[0]


def test_content_filter_is_recorded_and_does_not_retry(tmp_path: Path) -> None:
    model = "anthropic/claude-opus-5.5"
    transport = _ScriptedTransport(
        responses=(
            _tool(name="read_email", arguments={"email_id": "mail-util"}, model=model),
            _stop(content="done", model=model, cost=0.01),
            {
                "choices": [
                    {
                        "finish_reason": "content_filter",
                        "message": {
                            "content": None,
                            "refusal": "blocked",
                            "role": "assistant",
                        },
                    }
                ],
                "id": "gen-filter",
                "model": model,
                "provider": "Anthropic",
            },
        )
    )
    planner = _planner(model=model, transport=transport, tmp_path=tmp_path)
    result = run_research_episode(
        condition="off",
        planner=planner,
        library=SkillLibrary(root=tmp_path / "skills"),
        workspace=campaign_workspace(phrasing="policy"),
        task=campaign_task_by_id(task_id="e0-learn"),
    )
    assert result.content_filtered is True
    assert result.reflection_status == "content_filter"
    assert result.lessons == ()
    assert [step.tool for step in result.steps] == ["read_email"]
    assert len(transport.bodies) == 3
    assert planner.usage_records[-1]["cost_source"] == "content_filter_reserve"
    assert planner.usage_records[-1]["cost_usd"] == pytest.approx(expected=0.06)


def test_parallel_tool_calls_run_in_order_before_the_next_model_turn(tmp_path: Path) -> None:
    model = "deepseek/deepseek-v4.1-flash-1017"
    transport = _ScriptedTransport(
        responses=(
            {
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": None,
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "function": {
                                        "arguments": json.dumps({"email_id": "inv-100"}),
                                        "name": "read_email",
                                    },
                                    "id": "call-a",
                                    "type": "function",
                                },
                                {
                                    "function": {
                                        "arguments": json.dumps({"invoice_id": "INV-100"}),
                                        "name": "search_docs",
                                    },
                                    "id": "call-b",
                                    "type": "function",
                                },
                            ],
                        },
                    }
                ],
                "model": model,
                "provider": "TestProvider",
                "usage": _usage(cost=0.001),
            },
            _stop(content="done", model=model, cost=0.001),
        )
    )
    planner = _planner(model=model, transport=transport, tmp_path=tmp_path)
    result = run_research_episode(
        condition="off",
        planner=planner,
        library=SkillLibrary(root=tmp_path / "skills"),
        workspace=campaign_workspace(phrasing="policy"),
        task=campaign_task_by_id(task_id="e2-trigger"),
    )
    assert [step.tool for step in result.steps] == ["read_email", "search_docs"]
    assert len(transport.bodies) == 2
    followup = transport.bodies[1]["messages"]
    assert [message["role"] for message in followup] == [
        "system",
        "user",
        "assistant",
        "tool",
        "tool",
    ]


def test_load_openrouter_key_reads_the_env_file_without_a_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text(data="OPENROUTER_API_KEY=unit-test-key\n", encoding="utf-8")
    assert load_openrouter_key(env_path=env_path) == "unit-test-key"
    env_path.write_text(data="OTHER=1\n", encoding="utf-8")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(MissingConfigError):
        load_openrouter_key(env_path=env_path)
