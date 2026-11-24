"""Run the parsing probe and the Opus cost probe. Does not start the full grid."""

import json
import sys
from pathlib import Path

from skill_taint.errors import ConfigError
from skill_taint.grid import (
    ROOT,
    CampaignSpec,
    execute_campaign,
    is_empty_length,
    load_grid,
    results_root,
    utc_now,
)
from skill_taint.planners.openrouter import CostLedger, load_openrouter_key, scrub


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    if root != ROOT:
        raise ConfigError(f"script root {root} does not match package root {ROOT}")
    api_key = load_openrouter_key(env_path=root / ".env")
    try:
        _run(root=root, api_key=api_key)
    except SystemExit:
        raise
    except Exception as exc:
        message = scrub(text=f"{type(exc).__name__}: {exc}", secret=api_key)
        sys.stderr.write(message + "\n")
        raise SystemExit(1) from None


def _run(*, root: Path, api_key: str) -> None:
    grid = load_grid(path=root / "configs" / "grid.yaml")
    results = results_root(root=root)
    ledger = CostLedger(path=results / "cost_ledger.json", stop_usd=grid.stop_usd)
    meta_path = results / "run_meta.json"
    meta = _read_object(path=meta_path)
    if "pilot_started" not in meta:
        meta["pilot_started"] = utc_now()
    _write_json(path=meta_path, payload=meta)
    decision = {
        "drop_spotlight": False,
        "empty_length": False,
        "planning_max_tokens": grid.planning_max_tokens,
        "probes": [],
        "reflection_max_tokens": grid.reflection_max_tokens,
    }
    probes = (
        CampaignSpec(
            short="deepseek",
            slug="deepseek/deepseek-v4.1-flash-1017",
            phrasing="policy",
            condition="off",
            repeat=0,
            phase="committed",
        ),
        CampaignSpec(
            short="opus",
            slug="anthropic/claude-opus-5.5",
            phrasing="policy",
            condition="off",
            repeat=0,
            phase="committed",
        ),
    )
    for spec in probes:
        if not ledger.can_start_campaign():
            raise ConfigError("cost ledger already reached the stop before this probe")
        summary = execute_campaign(
            root=root,
            spec=spec,
            api_key=api_key,
            ledger=ledger,
            planning_max_tokens=int(decision["planning_max_tokens"]),
            reflection_max_tokens=int(decision["reflection_max_tokens"]),
        )
        decision["probes"].append(_probe_row(summary=summary))
        _print_summary(summary=summary)
        if summary.get("status") == "complete":
            continue
        if is_empty_length(summary=summary) and decision["empty_length"] is False:
            decision["empty_length"] = True
            decision["drop_spotlight"] = True
            decision["planning_max_tokens"] = 2000
            _write_json(path=results / "probe_decision.json", payload=decision)
            if not ledger.can_start_campaign():
                raise ConfigError("refusing to retry the probe after the stop was reached")
            retried = execute_campaign(
                root=root,
                spec=spec,
                api_key=api_key,
                ledger=ledger,
                planning_max_tokens=2000,
                reflection_max_tokens=int(decision["reflection_max_tokens"]),
                replace_incomplete=True,
            )
            decision["probes"].append(_probe_row(summary=retried))
            _print_summary(summary=retried)
            if is_empty_length(summary=retried) or retried.get("status") != "complete":
                _write_json(path=results / "probe_decision.json", payload=decision)
                raise ConfigError(
                    "probe still failed after planning_max_tokens=2000; full grid was not started"
                )
            continue
        _write_json(path=results / "probe_decision.json", payload=decision)
        raise ConfigError(
            f"probe {spec.campaign_id} failed before the grid: {summary.get('incomplete_reason')}"
        )
    _write_json(path=results / "probe_decision.json", payload=decision)
    meta = _read_object(path=meta_path)
    meta["pilot_finished"] = utc_now()
    meta["spent_usd_after_pilot"] = ledger.spent_usd
    meta["planning_max_tokens"] = decision["planning_max_tokens"]
    meta["drop_spotlight"] = decision["drop_spotlight"]
    _write_json(path=meta_path, payload=meta)
    sys.stdout.write(
        f"pilot done spent_usd={ledger.spent_usd:.6f} "
        f"planning_max_tokens={decision['planning_max_tokens']} "
        f"drop_spotlight={decision['drop_spotlight']}\n"
    )


def _probe_row(*, summary: dict[str, object]) -> dict[str, object]:
    usage = summary.get("usage")
    cost = None
    if isinstance(usage, dict):
        cost = usage.get("cost_usd")
    return {
        "campaign_id": summary.get("campaign_id"),
        "cost_usd": cost,
        "incomplete_reason": summary.get("incomplete_reason"),
        "returned_models": summary.get("returned_models"),
        "status": summary.get("status"),
    }


def _print_summary(*, summary: dict[str, object]) -> None:
    usage = summary.get("usage")
    cost = usage.get("cost_usd") if isinstance(usage, dict) else None
    score = summary.get("score")
    sys.stdout.write(
        f"{summary.get('campaign_id')} status={summary.get('status')} "
        f"cost_usd={cost} score={json.dumps(score, sort_keys=True)}\n"
    )
    skills = summary.get("skills")
    if isinstance(skills, list):
        for skill in skills:
            if isinstance(skill, dict):
                sys.stdout.write(
                    f"  skill label={skill.get('label')} body={skill.get('body')}\n"
                )
    if summary.get("incomplete_reason"):
        sys.stdout.write(f"  reason={summary.get('incomplete_reason')}\n")


def _read_object(*, path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ConfigError(f"{path.name} is not an object")
    return payload


def _write_json(*, path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        data=json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


if __name__ == "__main__":
    main()
