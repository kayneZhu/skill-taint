"""Probe one DeepSeek record-update run, then the plain grid, then formal if the ledger allows."""

import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from skill_taint.errors import ConfigError
from skill_taint.grid import (
    ROOT,
    CampaignSpec,
    execute_campaign,
    formal_record_specs,
    load_record_grid,
    load_summary,
    record_specs,
    results_root,
    summary_path,
    utc_now,
)
from skill_taint.metrics import record_metric_map, record_score_from_summary
from skill_taint.planners.openrouter import CostLedger, load_openrouter_key, scrub
from skill_taint.workspaces.invoice import RECORD_TASKS

_PROBE_SCORE_KEYS = (
    "benign_skill_loaded_e4",
    "benign_skill_stored",
    "benign_utility",
    "consulted_registry",
    "consulted_registry_e2",
    "consulted_registry_e3",
    "false_quarantine",
    "paid_correct_e2",
    "paid_correct_e3",
    "paid_unverified_e2",
    "paid_unverified_e3",
    "record_inconsistent",
    "record_inconsistent_quarantined",
)


def main(*, probe_only: bool) -> None:
    root = Path(__file__).resolve().parents[1]
    if root != ROOT:
        raise ConfigError(f"script root {root} does not match package root {ROOT}")
    api_key = load_openrouter_key(env_path=root / ".env")
    try:
        _run(root=root, api_key=api_key, probe_only=probe_only)
    except SystemExit:
        raise
    except Exception as exc:
        message = scrub(text=f"{type(exc).__name__}: {exc}", secret=api_key)
        sys.stderr.write(message + "\n")
        raise SystemExit(1) from None


def _run(*, root: Path, api_key: str, probe_only: bool) -> None:
    grid = load_record_grid(path=root / "configs" / "record_update.yaml")
    results = results_root(root=root)
    decision_path = results / "probe_decision.json"
    if not decision_path.is_file():
        raise ConfigError("probe_decision.json is missing; token limits are unknown")
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    if not isinstance(decision, dict):
        raise ConfigError("probe_decision.json is not an object")
    planning = decision.get("planning_max_tokens")
    reflection = decision.get("reflection_max_tokens")
    if planning != grid.planning_max_tokens or reflection != grid.reflection_max_tokens:
        raise ConfigError("record grid token limits do not match the committed probe decision")
    if not isinstance(planning, int) or not isinstance(reflection, int):
        raise ConfigError("probe token limits are not integers")
    ledger = CostLedger(path=results / "cost_ledger.json", stop_usd=grid.stop_usd)
    if not ledger.can_start_campaign():
        raise ConfigError("cost ledger already reached the stop")
    meta_path = results / "record_meta.json"
    meta = _read_object(path=meta_path)
    if "record_grid_started" not in meta:
        meta["record_grid_started"] = utc_now()
    meta["planning_max_tokens"] = planning
    meta["reflection_max_tokens"] = reflection
    meta["spent_usd_before"] = ledger.spent_usd
    _write_json(path=meta_path, payload=meta)
    probe = CampaignSpec(
        short="deepseek",
        slug="deepseek/deepseek-v4.1-flash-1017",
        phrasing="plain",
        condition="off",
        repeat=0,
        phase="record",
        family="record_update",
    )
    sys.stdout.write(f"record probe start spent_usd={ledger.spent_usd:.6f}\n")
    probe_summary = execute_campaign(
        root=root,
        spec=probe,
        api_key=api_key,
        ledger=ledger,
        planning_max_tokens=planning,
        reflection_max_tokens=reflection,
    )
    _print_probe(summary=probe_summary)
    _require_probe(summary=probe_summary)
    meta = _read_object(path=meta_path)
    meta["record_probe_finished"] = utc_now()
    meta["probe_campaign_id"] = probe.campaign_id
    meta["probe_status"] = probe_summary.get("status")
    _write_json(path=meta_path, payload=meta)
    if probe_only:
        sys.stdout.write(f"probe only spent_usd={ledger.spent_usd:.6f}\n")
        return
    specs = record_specs(grid=grid)
    if probe.campaign_id not in {spec.campaign_id for spec in specs}:
        raise ConfigError("probe campaign is not part of the plain record grid")
    instruction_costs = _instruction_max_costs(root=root)
    opus_cost = instruction_costs.get("anthropic/claude-opus-5.5")
    if opus_cost is None:
        raise ConfigError("no measured instruction-grid cost for Opus; refusing to guess concurrency")
    opus_limit = _opus_limit(concurrency=grid.concurrency_per_model, opus_cost=opus_cost)
    limits = {
        model.slug: (opus_limit if model.short == "opus" else grid.concurrency_per_model)
        for model in grid.models
    }
    meta["concurrency"] = limits
    _write_json(path=meta_path, payload=meta)
    sys.stdout.write(
        f"record grid start spent_usd={ledger.spent_usd:.6f} concurrency={limits}\n"
    )
    started = time.perf_counter()
    record_costs: dict[str, float] = {}
    _run_rounds(
        root=root,
        api_key=api_key,
        ledger=ledger,
        specs=specs,
        limits=limits,
        record_costs=record_costs,
        planning_max_tokens=planning,
        reflection_max_tokens=reflection,
        phase_name="record",
    )
    plain_elapsed = time.perf_counter() - started
    formal_note = _formal_note(
        grid_models=tuple(model.slug for model in grid.models),
        ledger_spent=ledger.spent_usd,
        stop_usd=grid.stop_usd,
        record_costs=record_costs,
        plain_elapsed=plain_elapsed,
    )
    formal_elapsed = 0.0
    if formal_note == "scheduled":
        formal_started = time.perf_counter()
        _run_rounds(
            root=root,
            api_key=api_key,
            ledger=ledger,
            specs=formal_record_specs(grid=grid),
            limits=limits,
            record_costs=record_costs,
            planning_max_tokens=planning,
            reflection_max_tokens=reflection,
            phase_name="record_formal",
        )
        formal_elapsed = time.perf_counter() - formal_started
        formal_note = "ran"
    meta = _read_object(path=meta_path)
    meta["record_grid_finished"] = utc_now()
    meta["record_wall_clock_seconds"] = plain_elapsed
    meta["formal"] = formal_note
    meta["formal_wall_clock_seconds"] = formal_elapsed
    meta["spent_usd_after"] = ledger.spent_usd
    _write_json(path=meta_path, payload=meta)
    sys.stdout.write(
        f"record grid done spent_usd={ledger.spent_usd:.6f} "
        f"plain_seconds={plain_elapsed:.1f} formal={formal_note} "
        f"formal_seconds={formal_elapsed:.1f}\n"
    )


def _require_probe(*, summary: dict[str, object]) -> None:
    if summary.get("status") != "complete":
        raise ConfigError(
            f"probe incomplete; grid was not started: {summary.get('incomplete_reason')}"
        )
    score = summary.get("score")
    if not isinstance(score, dict):
        raise ConfigError("probe score is missing")
    for key in _PROBE_SCORE_KEYS:
        if not isinstance(score.get(key), bool):
            raise ConfigError(f"probe score missing bool {key}")
    episodes = summary.get("episodes")
    if not isinstance(episodes, list):
        raise ConfigError("probe episodes are missing")
    task_ids = [episode.get("task_id") for episode in episodes if isinstance(episode, dict)]
    expected = [task.task_id for task in RECORD_TASKS]
    if task_ids != expected:
        raise ConfigError(f"probe episodes {task_ids} != {expected}")
    skills = summary.get("skills")
    if not isinstance(skills, list):
        raise ConfigError("probe skills are missing")
    usage = summary.get("usage")
    if not isinstance(usage, dict) or not isinstance(usage.get("cost_usd"), (int, float)):
        raise ConfigError("probe usage cost is missing")
    if isinstance(usage.get("cost_usd"), bool):
        raise ConfigError("probe usage cost is not a number")
    if summary.get("returned_models") != [summary.get("model")]:
        raise ConfigError(f"probe returned model {summary.get('returned_models')}")
    rescored = record_metric_map(score=record_score_from_summary(summary=summary))
    for key in _PROBE_SCORE_KEYS:
        if score.get(key) is not rescored[key]:
            raise ConfigError(
                f"probe metric {key} stored {score.get(key)} but rescored {rescored[key]}"
            )


def _print_probe(*, summary: dict[str, object]) -> None:
    usage = summary.get("usage")
    cost = usage.get("cost_usd") if isinstance(usage, dict) else None
    sys.stdout.write(
        f"{summary.get('campaign_id')} status={summary.get('status')} "
        f"cost_usd={cost} score={json.dumps(summary.get('score'), sort_keys=True)}\n"
    )
    skills = summary.get("skills")
    if isinstance(skills, list):
        for skill in skills:
            if isinstance(skill, dict):
                sys.stdout.write(
                    f"  skill label={skill.get('label')} episode={skill.get('episode_id')} "
                    f"body={skill.get('body')}\n"
                )
    episodes = summary.get("episodes")
    if isinstance(episodes, list):
        for episode in episodes:
            if isinstance(episode, dict):
                sys.stdout.write(
                    f"  episode {episode.get('task_id')} transfers={episode.get('transfers')} "
                    f"tools={[step.get('tool') for step in episode.get('steps') or [] if isinstance(step, dict)]}\n"
                )
    if summary.get("incomplete_reason"):
        sys.stdout.write(f"  reason={summary.get('incomplete_reason')}\n")


def _formal_note(
    *,
    grid_models: tuple[str, ...],
    ledger_spent: float,
    stop_usd: float,
    record_costs: dict[str, float],
    plain_elapsed: float,
) -> str:
    if ledger_spent >= stop_usd:
        return "stop reached before formal"
    if plain_elapsed > 25 * 60:
        return "plain grid exceeded 25 minutes"
    missing = [slug for slug in grid_models if slug not in record_costs]
    if missing:
        return "not scheduled; no completed plain cost for " + ", ".join(missing)
    per_model = 6
    projected = sum(record_costs[slug] * per_model for slug in grid_models)
    if ledger_spent + projected >= stop_usd:
        return (
            f"projected formal {projected:.4f} would reach the stop from {ledger_spent:.4f}"
        )
    return "scheduled"


def _run_rounds(
    *,
    root: Path,
    api_key: str,
    ledger: CostLedger,
    specs: tuple[CampaignSpec, ...],
    limits: dict[str, int],
    record_costs: dict[str, float],
    planning_max_tokens: int,
    reflection_max_tokens: int,
    phase_name: str,
) -> None:
    lock = threading.Lock()
    semaphores = {slug: threading.Semaphore(value=limit) for slug, limit in limits.items()}
    repeats = sorted({spec.repeat for spec in specs})
    for repeat in repeats:
        if not ledger.can_start_campaign():
            sys.stdout.write(f"{phase_name} stop before repeat {repeat}\n")
            return
        round_specs = tuple(spec for spec in specs if spec.repeat == repeat)
        errors: list[str] = []

        def worker(spec: CampaignSpec) -> None:
            semaphore = semaphores[spec.slug]
            with semaphore:
                if not ledger.can_start_campaign():
                    sys.stdout.write(
                        f"skip {spec.campaign_id} spent_usd={ledger.spent_usd:.6f}\n"
                    )
                    return
                existing = load_summary(
                    path=summary_path(root=root, campaign_id=spec.campaign_id)
                )
                if existing is not None and existing.get("status") == "complete":
                    _note_cost(summary=existing, record_costs=record_costs, lock=lock)
                    sys.stdout.write(f"keep {spec.campaign_id}\n")
                    return
                sys.stdout.write(f"start {spec.campaign_id}\n")
                try:
                    summary = execute_campaign(
                        root=root,
                        spec=spec,
                        api_key=api_key,
                        ledger=ledger,
                        planning_max_tokens=planning_max_tokens,
                        reflection_max_tokens=reflection_max_tokens,
                    )
                except Exception as exc:
                    message = scrub(text=f"{spec.campaign_id}: {exc}", secret=api_key)
                    with lock:
                        errors.append(message)
                    sys.stdout.write(message + "\n")
                    return
                _note_cost(summary=summary, record_costs=record_costs, lock=lock)
                score = summary.get("score")
                flags = ""
                if isinstance(score, dict):
                    flags = (
                        f" record={score.get('record_inconsistent')}"
                        f" unverified_e2={score.get('paid_unverified_e2')}"
                        f" correct_e2={score.get('paid_correct_e2')}"
                        f" unverified_e3={score.get('paid_unverified_e3')}"
                        f" correct_e3={score.get('paid_correct_e3')}"
                    )
                usage = summary.get("usage")
                cost = usage.get("cost_usd") if isinstance(usage, dict) else None
                sys.stdout.write(
                    f"done {spec.campaign_id} status={summary.get('status')} "
                    f"cost_usd={cost} spent_usd={ledger.spent_usd:.6f}{flags}\n"
                )

        with ThreadPoolExecutor(max_workers=sum(limits.values())) as pool:
            futures = [pool.submit(worker, spec) for spec in round_specs]
            for future in as_completed(futures):
                future.result()
        if errors:
            raise ConfigError("; ".join(errors))


def _note_cost(
    *,
    summary: dict[str, object],
    record_costs: dict[str, float],
    lock: threading.Lock,
) -> None:
    if summary.get("status") != "complete":
        return
    usage = summary.get("usage")
    model = summary.get("model")
    if not isinstance(model, str) or not isinstance(usage, dict):
        return
    cost = usage.get("cost_usd")
    if isinstance(cost, bool) or not isinstance(cost, (int, float)):
        return
    with lock:
        record_costs[model] = max(record_costs.get(model, 0.0), float(cost))


def _instruction_max_costs(*, root: Path) -> dict[str, float]:
    costs: dict[str, float] = {}
    directory = results_root(root=root) / "summaries"
    for path in directory.glob(pattern="*.json"):
        summary = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(summary, dict):
            raise ConfigError(f"{path.name} is not an object")
        if summary.get("phrasing") not in {"policy", "explicit"}:
            continue
        if summary.get("status") != "complete":
            continue
        model = summary.get("model")
        usage = summary.get("usage")
        if not isinstance(model, str) or not isinstance(usage, dict):
            continue
        cost = usage.get("cost_usd")
        if isinstance(cost, bool) or not isinstance(cost, (int, float)):
            continue
        costs[model] = max(costs.get(model, 0.0), float(cost))
    return costs


def _opus_limit(*, concurrency: int, opus_cost: float) -> int:
    if opus_cost > 0.5:
        return 1
    if opus_cost > 0.25:
        return 2
    return concurrency


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
    if len(sys.argv) == 1:
        main(probe_only=False)
    elif len(sys.argv) == 2 and sys.argv[1] == "--probe-only":
        main(probe_only=True)
    else:
        sys.stderr.write("usage: run_record_grid.py [--probe-only]\n")
        raise SystemExit(2)
