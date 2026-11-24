"""Load the committed grid and run one campaign.

Scripts decide the schedule. This module does not pick a different model when
a call fails, and it does not start a campaign once the ledger reaches the stop.
"""

import json
import traceback
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from skill_taint.agent import CampaignRun, run_campaign
from skill_taint.errors import ConfigError
from skill_taint.planners.openrouter import (
    CATALOG,
    REASONING_EFFORT,
    CostLedger,
    OpenRouterPlanner,
    scrub,
)
from skill_taint.skills import SkillLibrary
from skill_taint.workspaces.invoice import campaign_workspace

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, kw_only=True)
class ModelRow:
    short: str
    slug: str
    input_per_million: float
    output_per_million: float
    temperature: int | None


@dataclass(frozen=True, kw_only=True)
class GridConfig:
    stop_usd: float
    ceiling_usd: float
    planning_max_tokens: int
    reflection_max_tokens: int
    reasoning_effort: str
    repeats: int
    concurrency_per_model: int
    cells: tuple[tuple[str, str], ...]
    models: tuple[ModelRow, ...]


@dataclass(frozen=True, kw_only=True)
class CampaignSpec:
    short: str
    slug: str
    phrasing: str
    condition: str
    repeat: int
    phase: str

    @property
    def campaign_id(self) -> str:
        return f"{self.short}__{self.phrasing}__{self.condition}__r{self.repeat}"


def load_grid(*, path: Path) -> GridConfig:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ConfigError("grid.yaml is not a mapping")
    required = (
        "ceiling_usd",
        "concurrency_per_model",
        "models",
        "phrasings",
        "planning_max_tokens",
        "reasoning_effort",
        "reflection_max_tokens",
        "repeats",
        "stop_usd",
    )
    for key in required:
        if key not in loaded:
            raise ConfigError(f"grid.yaml missing {key}")
    if loaded["reasoning_effort"] != REASONING_EFFORT:
        raise ConfigError("grid reasoning_effort does not match the client")
    if loaded["repeats"] != 3:
        raise ConfigError("the committed grid uses 3 repeats")
    if loaded["stop_usd"] != 9.0 or loaded["ceiling_usd"] != 10.0:
        raise ConfigError("grid budget does not match the committed stop and ceiling")
    if not isinstance(loaded["phrasings"], dict):
        raise ConfigError("grid phrasings is not a mapping")
    cells: list[tuple[str, str]] = []
    for phrasing, conditions in loaded["phrasings"].items():
        if not isinstance(phrasing, str) or not isinstance(conditions, list):
            raise ConfigError("grid phrasing entry is malformed")
        for condition in conditions:
            if not isinstance(condition, str):
                raise ConfigError("grid condition is not a string")
            cells.append((phrasing, condition))
    if not isinstance(loaded["models"], list) or len(loaded["models"]) != 3:
        raise ConfigError("grid must list the three committed models")
    models: list[ModelRow] = []
    for item in loaded["models"]:
        if not isinstance(item, dict):
            raise ConfigError("grid model is not a mapping")
        for key in ("input_per_million", "output_per_million", "short", "slug", "temperature"):
            if key not in item:
                raise ConfigError(f"grid model missing {key}")
        slug = item["slug"]
        if slug not in CATALOG:
            raise ConfigError(f"grid model is not in the client catalog: {slug}")
        spec = CATALOG[slug]
        if item["input_per_million"] != spec.input_per_million:
            raise ConfigError(f"input price mismatch for {slug}")
        if item["output_per_million"] != spec.output_per_million:
            raise ConfigError(f"output price mismatch for {slug}")
        if item["temperature"] != spec.temperature:
            raise ConfigError(f"temperature mismatch for {slug}")
        models.append(
            ModelRow(
                short=item["short"],
                slug=slug,
                input_per_million=item["input_per_million"],
                output_per_million=item["output_per_million"],
                temperature=item["temperature"],
            )
        )
    return GridConfig(
        stop_usd=float(loaded["stop_usd"]),
        ceiling_usd=float(loaded["ceiling_usd"]),
        planning_max_tokens=int(loaded["planning_max_tokens"]),
        reflection_max_tokens=int(loaded["reflection_max_tokens"]),
        reasoning_effort=str(loaded["reasoning_effort"]),
        repeats=int(loaded["repeats"]),
        concurrency_per_model=int(loaded["concurrency_per_model"]),
        cells=tuple(cells),
        models=tuple(models),
    )


def committed_specs(*, grid: GridConfig, drop_spotlight: bool) -> tuple[CampaignSpec, ...]:
    specs: list[CampaignSpec] = []
    for repeat in range(grid.repeats):
        for model in grid.models:
            for phrasing, condition in grid.cells:
                if drop_spotlight and condition == "spotlight":
                    continue
                specs.append(
                    CampaignSpec(
                        short=model.short,
                        slug=model.slug,
                        phrasing=phrasing,
                        condition=condition,
                        repeat=repeat,
                        phase="committed",
                    )
                )
    return tuple(specs)


def extension_specs(*, grid: GridConfig) -> tuple[CampaignSpec, ...]:
    specs: list[CampaignSpec] = []
    for repeat in range(grid.repeats):
        for model in grid.models:
            for condition in ("spotlight", "quarantine"):
                specs.append(
                    CampaignSpec(
                        short=model.short,
                        slug=model.slug,
                        phrasing="explicit",
                        condition=condition,
                        repeat=repeat,
                        phase="extension",
                    )
                )
    return tuple(specs)


def results_root(*, root: Path) -> Path:
    path = root / "results"
    (path / "summaries").mkdir(parents=True, exist_ok=True)
    (path / "raw").mkdir(parents=True, exist_ok=True)
    (path / "libraries").mkdir(parents=True, exist_ok=True)
    return path


def summary_path(*, root: Path, campaign_id: str) -> Path:
    return results_root(root=root) / "summaries" / f"{campaign_id}.json"


def load_summary(*, path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ConfigError(f"summary is not an object: {path.name}")
    return payload


def execute_campaign(
    *,
    root: Path,
    spec: CampaignSpec,
    api_key: str,
    ledger: CostLedger,
    planning_max_tokens: int,
    reflection_max_tokens: int,
    transport: object | None = None,
    replace_incomplete: bool = False,
) -> dict[str, object]:
    path = summary_path(root=root, campaign_id=spec.campaign_id)
    existing = load_summary(path=path)
    if existing is not None and existing.get("status") == "complete":
        return existing
    if existing is not None and not replace_incomplete:
        return existing
    if api_key == "":
        raise ConfigError("api key is empty")
    library_dir = results_root(root=root) / "libraries" / spec.campaign_id
    if replace_incomplete and library_dir.exists():
        for child in library_dir.iterdir():
            if child.is_file():
                child.unlink()
    raw_path = results_root(root=root) / "raw" / f"{spec.campaign_id}.jsonl"
    if replace_incomplete and raw_path.exists():
        raw_path.unlink()
    library = SkillLibrary(root=library_dir)
    workspace = campaign_workspace(phrasing=spec.phrasing)
    used: list[OpenRouterPlanner] = []

    def factory() -> OpenRouterPlanner:
        if transport is None:
            from skill_taint.llm import UrllibTransport

            chosen = UrllibTransport()
        else:
            chosen = transport
        planner = OpenRouterPlanner(
            api_key=api_key,
            model=spec.slug,
            transport=chosen,
            ledger=ledger,
            campaign_id=spec.campaign_id,
            planning_max_tokens=planning_max_tokens,
            reflection_max_tokens=reflection_max_tokens,
            timeout_seconds=240.0,
            raw_path=raw_path,
        )
        used.append(planner)
        return planner

    started = datetime.now(tz=timezone.utc).isoformat()
    run: CampaignRun | None = None
    error: str | None = None
    try:
        run = run_campaign(
            condition=spec.condition,
            phrasing=spec.phrasing,
            planner_factory=factory,
            library=library,
            workspace=workspace,
        )
    except Exception as exc:
        error = scrub(text=f"{type(exc).__name__}: {exc}", secret=api_key)
        traced = scrub(text=traceback.format_exc(), secret=api_key)
        error_path = results_root(root=root) / "last_error.txt"
        error_path.write_text(data=traced, encoding="utf-8")
        payload = _payload(
            spec=spec,
            run=None,
            library=library,
            planners=used,
            planning_max_tokens=planning_max_tokens,
            reflection_max_tokens=reflection_max_tokens,
            started=started,
            incomplete_reason=error,
        )
        _write_summary(path=path, payload=payload, api_key=api_key)
        raise ConfigError(error) from None
    reason = None if run.status == "complete" else run.incomplete_reason
    payload = _payload(
        spec=spec,
        run=run,
        library=library,
        planners=used,
        planning_max_tokens=planning_max_tokens,
        reflection_max_tokens=reflection_max_tokens,
        started=started,
        incomplete_reason=reason,
    )
    _write_summary(path=path, payload=payload, api_key=api_key)
    del error
    return payload


def is_empty_length(*, summary: Mapping[str, object]) -> bool:
    if summary.get("status") != "incomplete":
        return False
    reason = summary.get("incomplete_reason")
    if not isinstance(reason, str):
        return False
    return "empty content" in reason and "length" in reason


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _write_summary(*, path: Path, payload: dict[str, object], api_key: str) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if api_key in text:
        raise ConfigError("refusing to write a summary that contains the API key")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(data=text, encoding="utf-8")
    temporary.replace(path)


def _payload(
    *,
    spec: CampaignSpec,
    run: CampaignRun | None,
    library: SkillLibrary,
    planners: Sequence[OpenRouterPlanner],
    planning_max_tokens: int,
    reflection_max_tokens: int,
    started: str,
    incomplete_reason: str | None,
) -> dict[str, object]:
    records: list[dict[str, object]] = []
    for planner in planners:
        records.extend(planner.usage_records)
    usage = _usage_totals(records=records)
    skills = [
        {
            "body": skill.body,
            "derived_from": list(skill.derived_from),
            "episode_id": skill.episode_id,
            "label": skill.label.value,
            "skill_id": skill.skill_id,
        }
        for skill in library.all()
    ]
    episodes: list[dict[str, object]] = []
    score: dict[str, object] | None = None
    status = "incomplete"
    if run is not None:
        status = run.status
        episodes = [_episode_dict(episode=episode) for episode in run.episodes]
        if run.score is not None:
            score = {
                "benign_skill_loaded_e4": run.score.benign_skill_loaded_e4,
                "benign_skill_stored": run.score.benign_skill_stored,
                "benign_utility": run.score.benign_utility,
                "contaminated": run.score.contaminated,
                "contaminated_quarantined": run.score.contaminated_quarantined,
                "contaminated_skill_ids": list(run.score.contaminated_skill_ids),
                "false_quarantine": run.score.false_quarantine,
                "one_shot": run.score.one_shot,
                "paraphrased": run.score.paraphrased,
                "spread": run.score.spread,
                "trigger": run.score.trigger,
                "verbatim": run.score.verbatim,
            }
    return {
        "campaign_id": spec.campaign_id,
        "condition": spec.condition,
        "episodes": episodes,
        "finished": utc_now(),
        "incomplete_reason": incomplete_reason,
        "model": spec.slug,
        "phase": spec.phase,
        "phrasing": spec.phrasing,
        "planning_max_tokens": planning_max_tokens,
        "providers": usage["providers"],
        "reflection_max_tokens": reflection_max_tokens,
        "repeat": spec.repeat,
        "returned_models": usage["returned_models"],
        "score": score,
        "short": spec.short,
        "skills": skills,
        "started": started,
        "status": status,
        "usage": usage["totals"],
    }


def _episode_dict(*, episode: object) -> dict[str, object]:
    from skill_taint.agent import ResearchEpisodeResult

    if not isinstance(episode, ResearchEpisodeResult):
        raise ConfigError("episode result has the wrong type")
    return {
        "conflict_bodies": list(episode.conflict_bodies),
        "deletes": list(episode.effects.deletes),
        "lesson_bodies": [skill.body for skill in episode.lessons],
        "loaded_skill_ids": list(episode.loaded_skill_ids),
        "reflection_status": episode.reflection_status,
        "rejected_bodies": list(episode.rejected_bodies),
        "sends": list(episode.effects.sends),
        "step_limit_hit": episode.step_limit_hit,
        "steps": [
            {
                "arguments": dict(step.arguments),
                "executed": step.executed,
                "tool": step.tool,
            }
            for step in episode.steps
        ],
        "task_id": episode.task_id,
        "transfers": [list(item) for item in episode.effects.transfers],
        "writes": [
            {"content": content, "path": path} for path, content in episode.effects.writes
        ],
    }


def _usage_totals(*, records: Sequence[Mapping[str, object]]) -> dict[str, object]:
    prompt = 0
    completion = 0
    reasoning = 0
    reasoning_missing = 0
    prompt_missing = 0
    completion_missing = 0
    cost = 0.0
    returned: list[str] = []
    providers: list[str] = []
    for record in records:
        prompt_tokens = record.get("prompt_tokens")
        completion_tokens = record.get("completion_tokens")
        reasoning_tokens = record.get("reasoning_tokens")
        if isinstance(prompt_tokens, int) and not isinstance(prompt_tokens, bool):
            prompt += prompt_tokens
        else:
            prompt_missing += 1
        if isinstance(completion_tokens, int) and not isinstance(completion_tokens, bool):
            completion += completion_tokens
        else:
            completion_missing += 1
        if isinstance(reasoning_tokens, int) and not isinstance(reasoning_tokens, bool):
            reasoning += reasoning_tokens
        else:
            reasoning_missing += 1
        cost_usd = record.get("cost_usd")
        if isinstance(cost_usd, (int, float)) and not isinstance(cost_usd, bool):
            cost += float(cost_usd)
        model = record.get("returned_model")
        if isinstance(model, str) and model not in returned:
            returned.append(model)
        provider = record.get("provider")
        if isinstance(provider, str) and provider not in providers:
            providers.append(provider)
    return {
        "providers": providers,
        "returned_models": returned,
        "totals": {
            "calls": len(records),
            "completion_tokens": completion,
            "completion_tokens_missing": completion_missing,
            "cost_usd": cost,
            "prompt_tokens": prompt,
            "prompt_tokens_missing": prompt_missing,
            "reasoning_tokens": reasoning,
            "reasoning_tokens_missing": reasoning_missing,
        },
    }
