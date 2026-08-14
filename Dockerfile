# docker-library/python publishes no free-threaded tags (issue #1082), so the
# interpreter comes from uv — which is the recommended way to get one anyway.
# .python-version pins it; bump there, not here.
FROM debian:trixie-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/opt/python

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=.python-version,target=.python-version \
    uv python install

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=.python-version,target=.python-version \
    uv sync --locked --no-install-project --no-dev

COPY pyproject.toml uv.lock README.md .python-version ./
COPY src/ ./src/

RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev


FROM debian:trixie-slim

# libpq5 because psycopg is the pure-python build — psycopg-binary ships no
# free-threaded wheels, and pure psycopg loads libpq at runtime.
# hadolint ignore=DL3008
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --create-home app

COPY --from=builder --chown=app:app /opt/python /opt/python
COPY --from=builder --chown=app:app /app /app

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
USER 10001
EXPOSE 8000

CMD ["uvicorn", "old_news.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
