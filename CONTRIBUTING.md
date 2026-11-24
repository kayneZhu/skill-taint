# Contributing

Issues and pull requests are welcome. The published numbers in `docs/report.md` are a measurement record. Do not edit those rates by hand.

## Setup

Install [uv](https://docs.astral.sh/uv/), then:

```bash
uv sync
uv run pytest
```

Tests use a fake transport. They do not call OpenRouter and they do not read a live API key. Continuous integration runs the same `uv run pytest` command.

## Secrets

Copy `.env.example` to `.env` only on your machine, and only if you intend to pay for a live grid. `.env` is gitignored. Do not commit keys, authorization headers, or a filled-in env file.

## Style

The package is `skill_taint`. The command is `skill-taint` (`skill-integrity` calls the same function). Pass arguments by keyword at call sites. Raise on a contract violation instead of substituting another behavior.

## Results

`results/summaries/` and `results/*.json` are the inputs to `scripts/make_report.py`. `results/raw/` is the committed call log. Rebuilding the report does not call a model:

```bash
uv run python scripts/make_report.py
```

A live grid writes into `results/`, continues the cost ledger, and keeps campaigns that are already marked complete. Do not replace a published summary in order to change a rate.
