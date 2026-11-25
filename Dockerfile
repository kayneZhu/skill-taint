# Locked environment for the measurement harness.
# The default command runs pytest and does not call OpenRouter.
# The campaign viewer stays on the host: make view
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.10.7 /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1

COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
COPY tests ./tests
COPY configs ./configs
COPY scripts ./scripts
COPY results ./results
COPY docs ./docs

RUN uv sync --frozen --group dev \
    && useradd --create-home --uid 10001 app \
    && chown -R app:app /app

USER app
CMD ["uv", "run", "pytest"]
