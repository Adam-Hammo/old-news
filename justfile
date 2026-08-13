set dotenv-load
export PICCOLO_CONF := "old_news.db.piccolo_conf"

default:
    @just --list

install:
    uv sync --all-extras
    uv run pre-commit install --install-hooks

# --- local running ---

up:
    docker compose up -d --build
    @just wait
    @echo "api      http://localhost:${API_HOST_PORT:-8000}"
    @echo "schema   http://localhost:${API_HOST_PORT:-8000}/schema"

down:
    docker compose down

# Also drops the pgdata volume.
nuke:
    docker compose down -v

logs service="":
    docker compose logs -f {{ service }}

wait:
    @until docker compose exec -T db pg_isready -U old_news -d old_news >/dev/null 2>&1; do sleep 1; done

psql:
    docker compose exec db psql -U old_news -d old_news

# Run the API on the host against the compose Postgres.
serve:
    uv run python -m old_news

worker:
    uv run procrastinate --app=old_news.tasks.app worker

# --- database ---

migrate:
    uv run python -m old_news.db.migrate

migration name:
    uv run piccolo migrations new old_news --auto --desc="{{ name }}"

# --- backups ---

backup:
    docker compose run --rm backup backup

# Destructive: overwrites the database with the latest snapshot.
restore snapshot="latest":
    docker compose run --rm backup restore {{ snapshot }}

# Writes a canary, backs up, destroys it, restores, checks it came back.
backup-verify:
    docker compose run --rm backup verify-restore

# --- quality ---

# Everything. `just test unit` for the fast, Docker-free subset.
test suite="" *args:
    uv run pytest {{ if suite == "" { "tests" } else { "tests/" + suite } }} {{ args }}

cov:
    uv run pytest --cov --cov-report=term-missing

# Every hook against every file — the same set CI runs.
lint *hooks:
    uv run pre-commit run --all-files {{ hooks }}

# Install the git hooks. `just install` already does this.
hooks:
    uv run pre-commit install --install-hooks

# Bump every pinned hook revision.
hooks-update:
    uv run pre-commit autoupdate

# Run the hooks over staged changes only, as a commit would.
hooks-staged:
    uv run pre-commit run

fmt:
    uv run ruff format .
    uv run ruff check --fix .

types:
    uv run ty check

# Known vulnerabilities in the locked dependency set.
audit:
    uv audit --preview-features audit-command

check: lint test

# --- images ---

# Cross-build for the Oracle box before pushing.
build-arm64:
    docker build --platform linux/arm64 -t old-news:arm64 .
    docker build --platform linux/arm64 -t old-news-postgres:arm64 -f docker/postgres.Dockerfile docker

# --- infrastructure ---

# The Pulumi CLI is a Go binary, not a Python package: `brew install pulumi`.

[working-directory('infra')]
tf-preview: _infra-env
    pulumi preview

[working-directory('infra')]
tf-up: _infra-env
    pulumi up

# Drift check: fails if the live cloud no longer matches the program.
[working-directory('infra')]
tf-drift: _infra-env
    pulumi preview --refresh --expect-no-changes

[working-directory('infra')]
_infra-env:
    uv sync --quiet

# Deploy an exact image tag; the deploy workflow runs this same recipe. Needs
# PULUMI_ACCESS_TOKEN. No _infra-env: `stack output` doesn't run the program.
[working-directory('infra')]
deploy tag:
    #!/usr/bin/env bash
    set -euo pipefail
    vars=$(mktemp)  # 0600
    trap 'rm -f "$vars"' EXIT
    pulumi stack output --json --show-secrets --stack prod >"$vars"
    cd ansible
    uv run --group deploy ansible-playbook playbook.yml -e "@$vars" -e image_tag={{ tag }}

# One-off: move the box onto a tagged Tailscale identity. Expect it to fail — it
# drops the connection it runs over.
[working-directory('infra')]
retag:
    #!/usr/bin/env bash
    set -euo pipefail
    vars=$(mktemp)
    trap 'rm -f "$vars"' EXIT
    pulumi stack output --json --show-secrets --stack prod >"$vars"
    cd ansible
    uv run --group deploy ansible-playbook playbook.yml --tags tailscale \
      -e "@$vars" -e tailscale_retag=true
