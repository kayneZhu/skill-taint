"""Command line. `--backend openai` raises if configuration is missing."""

import argparse
import os
import sys
from pathlib import Path

from skill_taint.errors import ConfigError, MissingConfigError
from skill_taint.evaluate import COMPARE_DEFENSES, run_mock_compare, run_one
from skill_taint.llm import OpenAIPlanner, UrllibTransport
from skill_taint.mock import MockPlanner


def main(*, argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="skill-integrity")
    parser.add_argument("--backend", choices=("mock", "openai"), required=True)
    parser.add_argument(
        "--defense",
        choices=("off", "segment", "episode", "gate", "compare"),
        required=True,
    )
    parser.add_argument("--workdir", required=True)
    parser.add_argument(
        "--endorse",
        action="store_true",
        help="Approve every endorsement request. Default is to deny. Not a defense.",
    )
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    args = parser.parse_args(args=argv)
    workdir = Path(args.workdir)
    if args.backend == "mock":
        if args.model is not None or args.base_url is not None:
            raise ConfigError("--model and --base-url require --backend openai")
        if args.defense == "compare":
            if args.endorse:
                raise ConfigError("--endorse cannot be combined with --defense compare")
            report = run_mock_compare(workdir=workdir)
        else:
            report = run_one(
                defense=args.defense,
                endorse=args.endorse,
                workdir=workdir,
                planner=MockPlanner(),
                heading=(
                    "planner: scripted mock (not a language model)",
                    "real_llm_results: not run",
                    f"defense: {args.defense}",
                    f"endorse: {str(args.endorse).lower()}",
                ),
            )
    elif args.backend == "openai":
        if args.defense == "compare":
            raise ConfigError("--defense compare is only defined for --backend mock")
        if args.defense not in COMPARE_DEFENSES:
            raise ConfigError(f"unknown defense {args.defense}")
        settings = resolve_openai_settings(model=args.model, base_url=args.base_url)
        planner = OpenAIPlanner(
            api_key=settings.api_key,
            base_url=settings.base_url,
            model=settings.model,
            transport=UrllibTransport(),
        )
        report = run_one(
            defense=args.defense,
            endorse=args.endorse,
            workdir=workdir,
            planner=planner,
            heading=(
                "planner: openai-compatible API",
                f"model: {settings.model}",
                f"defense: {args.defense}",
                f"endorse: {str(args.endorse).lower()}",
            ),
        )
    else:
        raise ConfigError(f"unknown backend {args.backend}")
    sys.stdout.write(report)


class _Settings:
    def __init__(self, *, api_key: str, base_url: str, model: str) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model


def resolve_openai_settings(*, model: str | None, base_url: str | None) -> _Settings:
    resolved_model = _pick(flag=model, flag_name="--model", env_name="OPENAI_MODEL")
    resolved_base = _pick(flag=base_url, flag_name="--base-url", env_name="OPENAI_BASE_URL")
    resolved_key = _pick(flag=None, flag_name="OPENAI_API_KEY", env_name="OPENAI_API_KEY")
    missing: list[str] = []
    if resolved_key is None:
        missing.append("OPENAI_API_KEY")
    if resolved_base is None:
        missing.append("OPENAI_BASE_URL")
    if resolved_model is None:
        missing.append("OPENAI_MODEL")
    if missing:
        raise MissingConfigError(missing=tuple(missing))
    if resolved_key is None or resolved_base is None or resolved_model is None:
        raise MissingConfigError(missing=("openai settings",))
    return _Settings(api_key=resolved_key, base_url=resolved_base, model=resolved_model)


def _pick(*, flag: str | None, flag_name: str, env_name: str) -> str | None:
    if flag is not None:
        if flag == "":
            raise MissingConfigError(missing=(f"{flag_name} is empty",))
        return flag
    if env_name not in os.environ:
        return None
    value = os.environ[env_name]
    if value == "":
        raise MissingConfigError(missing=(f"{env_name} is empty",))
    return value
