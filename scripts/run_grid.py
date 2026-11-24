"""Run the committed grid, then optional explicit defenses if budget and time remain."""

import json
import sys
import threading
import time
from pathlib import Path

from skill_taint.errors import ConfigError
from skill_taint.grid import (
    ROOT,
    CampaignSpec,
    committed_specs,
    execute_campaign,
    extension_specs,
    load_grid,
    load_summary,
    results_root,
    summary_path,
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
    decision_path = results / "probe_decision.json"
    if not decision_path.is_file():
        raise ConfigError("probe_decision.json is missing; run scripts/pilot.py first")
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    if not isinstance(decision, dict):
        raise ConfigError("probe_decision.json is not an object")
    for key in ("drop_spotlight", "planning_max_tokens", "reflection_max_tokens"):
        if key not in decision:
            raise ConfigError(f"probe decision missing {key}")
    planning = decision["planning_max_tokens"]
    reflection = decision["reflection_max_tokens"]
    drop_spotlight = decision["drop_spotlight"]
    if not isinstance(planning, int) or not isinstance(reflection, int):
        raise ConfigError("probe token limits are not integers")
    if not isinstance(drop_spotlight, bool):
        raise ConfigError("drop_spotlight is not a bool")
    ledger = CostLedger(path=results / "cost_ledger.json", stop_usd=grid.stop_usd)
    meta_path = results / "run_meta.json"
    meta = _read_object(path=meta_path)
    meta["grid_started"] = utc_now()
    meta["planning_max_tokens"] = planning
    meta["reflection_max_tokens"] = reflection
    meta["drop_spotlight"] = drop_spotlight
    _write_json(path=meta_path, payload=meta)
    specs = committed_specs(grid=grid, drop_spotlight=drop_spotlight)
    estimates = _seed_estimates(root=root, specs=specs)
    opus_limit = _opus_limit(
        concurrency=grid.concurrency_per_model,
        opus_cost=estimates.get("anthropic/claude-opus-5.5", 1.0),
    )
    limits = {
        model.slug: (opus_limit if model.short == "opus" else grid.concurrency_per_model)
        for model in grid.models
    }
    meta["concurrency"] = limits
    _write_json(path=meta_path, payload=meta)
    sys.stdout.write(
        f"grid start spent_usd={ledger.spent_usd:.6f} concurrency={limits} "
        f"planning_max_tokens={planning} drop_spotlight={drop_spotlight}\n"
    )
    started = time.perf_counter()
    _run_rounds(
        root=root,
        api_key=api_key,
        ledger=ledger,
        specs=specs,
        limits=limits,
        estimates=estimates,
        planning_max_tokens=planning,
        reflection_max_tokens=reflection,
        phase_name="committed",
    )
    elapsed = time.perf_counter() - started
    extension_note = "not scheduled"
    if drop_spotlight:
        extension_note = "spotlight was dropped after the empty-length probe"
    elif not ledger.can_start_campaign():
        extension_note = "stop reached before the extension"
    elif elapsed > 45 * 60:
        extension_note = "committed grid used more than 45 minutes"
    else:
        projected = _projected_extension(estimates=estimates, campaigns=18)
        if ledger.spent_usd + projected >= grid.stop_usd:
            extension_note = (
                f"projected extension {projected:.4f} would reach the stop "
                f"from {ledger.spent_usd:.4f}"
            )
        else:
            extension_note = "scheduled"
            _run_rounds(
                root=root,
                api_key=api_key,
                ledger=ledger,
                specs=extension_specs(grid=grid),
                limits=limits,
                estimates=estimates,
                planning_max_tokens=planning,
                reflection_max_tokens=reflection,
                phase_name="extension",
            )
    meta = _read_object(path=meta_path)
    meta["grid_finished"] = utc_now()
    meta["spent_usd"] = ledger.spent_usd
    meta["extension"] = extension_note
    meta["wall_clock_grid_seconds"] = time.perf_counter() - started
    _write_json(path=meta_path, payload=meta)
    sys.stdout.write(
        f"grid done spent_usd={ledger.spent_usd:.6f} "
        f"wall_clock_grid_seconds={meta['wall_clock_grid_seconds']:.1f} "
        f"extension={extension_note}\n"
    )


def _run_rounds(
    *,
    root: Path,
    api_key: str,
    ledger: CostLedger,
    specs: tuple[CampaignSpec, ...],
    limits: dict[str, int],
    estimates: dict[str, float],
    planning_max_tokens: int,
    reflection_max_tokens: int,
    phase_name: str,
) -> None:
    lock = threading.Lock()
    semaphores = {slug: threading.Semaphore(limit) for slug, limit in limits.items()}
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
                estimate = estimates.get(spec.slug, 0.0)
                if ledger.spent_usd >= 9.0 or (
                    estimate > 0 and ledger.spent_usd + estimate > 9.8
                ):
                    sys.stdout.write(
                        f"skip {spec.campaign_id} spent_usd={ledger.spent_usd:.6f} "
                        f"estimate={estimate:.6f}\n"
                    )
                    return
                existing = load_summary(
                    path=summary_path(root=root, campaign_id=spec.campaign_id)
                )
                if existing is not None and existing.get("status") == "complete":
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
                usage = summary.get("usage")
                cost = 0.0
                if isinstance(usage, dict) and isinstance(usage.get("cost_usd"), (int, float)):
                    cost = float(usage["cost_usd"])
                with lock:
                    previous = estimates.get(spec.slug, 0.0)
                    if cost > previous:
                        estimates[spec.slug] = cost
                sys.stdout.write(
                    f"done {spec.campaign_id} status={summary.get('status')} "
                    f"cost_usd={cost:.6f} spent_usd={ledger.spent_usd:.6f}\n"
                )

        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=sum(limits.values())) as pool:
            futures = [pool.submit(worker, spec) for spec in round_specs]
            for future in as_completed(futures):
                future.result()
        if errors:
            raise ConfigError("; ".join(errors))


def _seed_estimates(*, root: Path, specs: tuple[CampaignSpec, ...]) -> dict[str, float]:
    estimates: dict[str, float] = {}
    for spec in specs:
        summary = load_summary(path=summary_path(root=root, campaign_id=spec.campaign_id))
        if summary is None:
            continue
        usage = summary.get("usage")
        if not isinstance(usage, dict):
            continue
        cost = usage.get("cost_usd")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool):
            estimates[spec.slug] = max(estimates.get(spec.slug, 0.0), float(cost))
    if "anthropic/claude-opus-5.5" in estimates and "google/gemini-4-hydrogen" not in estimates:
        estimates["google/gemini-4-hydrogen"] = estimates["anthropic/claude-opus-5.5"] * (7.5 / 20.0)
    return estimates


def _opus_limit(*, concurrency: int, opus_cost: float) -> int:
    if opus_cost > 0.5:
        return 1
    if opus_cost > 0.25:
        return 2
    return concurrency


def _projected_extension(*, estimates: dict[str, float], campaigns: int) -> float:
    per_model = campaigns // 3
    total = 0.0
    for slug, cost in estimates.items():
        total += cost * per_model
    if not estimates:
        return 9.0
    return total


def _read_object(*, path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ConfigError(f"{path.name} is not an object")
    return payload


def _write_json(*, path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        data=json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


if __name__ == "__main__":
    main()
