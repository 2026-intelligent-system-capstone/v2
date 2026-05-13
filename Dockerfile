FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN groupadd --system app \
    && useradd --system --gid app --home /app app

COPY --from=ghcr.io/astral-sh/uv:0.9.17 /uv /uvx /usr/local/bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN mkdir -p /app/data/artifacts \
    && chown -R app:app /app

USER app

EXPOSE 8000 8501

CMD ["uvicorn", "services.api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
