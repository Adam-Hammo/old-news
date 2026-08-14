set dotenv-load

# Where the operational recipes act. Empty is the local compose stack; set a
# tailnet host to reach the box instead:
#
#   just host=rss-01.tailed73bc.ts.net logs worker
#   just host=rss-01.tailed73bc.ts.net opml-import
#
# Lifecycle recipes (up, down, nuke) are deliberately local-only — the box is
# deployed with `just deploy`, never built in place.
host := ""
remote_dir := "/opt/old-news"

# --project-directory rather than `cd … &&`, so the remote command needs no shell
# quoting. Two forms because a pty and a pipe are mutually exclusive: -t breaks
# stdin redirection, and no -t makes psql unusable.
compose := if host == "" { "docker compose" } else { "ssh " + host + " docker compose --project-directory " + remote_dir }
compose_tty := if host == "" { "docker compose" } else { "ssh -t " + host + " docker compose --project-directory " + remote_dir }

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
    @echo "admin    http://localhost:${API_HOST_PORT:-8000}/admin"

down:
    docker compose down

# Also drops the pgdata volume.
nuke:
    docker compose down -v

wait:
    @until docker compose exec -T db pg_isready -U old_news -d old_news >/dev/null 2>&1; do sleep 1; done

# Run the API on the host against the compose Postgres.
serve:
    uv run python -m old_news

worker:
    uv run python -m old_news worker

# --- operating (honour `host`) ---

ps:
    {{ compose }} ps

logs service="":
    {{ compose_tty }} logs -f {{ service }}

psql:
    {{ compose_tty }} exec db psql -U old_news -d old_news

# --- database ---

migrate:
    uv run python -m old_news.db.migrate

migration name:
    uv run alembic revision --autogenerate -m "{{ name }}"

# Show the current revision and what is pending.
migration-status:
    uv run alembic current
    uv run alembic history --indicate-current

rollback steps="-1":
    uv run alembic downgrade {{ steps }}

# Hash a password for the admin console — prints a line for .env or pulumi config.
admin-password:
    @uv run python -m old_news admin-password

# --- subscriptions (honour `host`) ---

# Piped rather than copied, so it works against a read-only container.
opml-import path="local/feeds.opml":
    {{ compose }} exec -T app python -m old_news opml import - < {{ path }}

# Writes to stdout: `just opml-export > local/feeds.opml` to round-trip.
opml-export:
    @{{ compose }} exec -T app python -m old_news opml export

# --- backups (honour `host`) ---

backup:
    {{ compose }} run --rm backup backup

# Destructive: overwrites the database with the latest snapshot.
restore snapshot="latest":
    {{ compose }} run --rm backup restore {{ snapshot }}

# Writes a canary, backs up, destroys it, restores, checks it came back.
backup-verify:
    {{ compose }} run --rm backup verify-restore

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
infra-preview: _infra-env
    pulumi preview

[working-directory('infra')]
infra-up: _infra-env
    pulumi up

# Drift check: fails if the live cloud no longer matches the program.
[working-directory('infra')]
infra-drift: _infra-env
    pulumi preview --refresh --expect-no-changes

# Dependabot doesn't watch infra/. Check `just infra-drift` before `just infra-up`.
[working-directory('infra')]
infra-update:
    uv lock --upgrade

[working-directory('infra')]
_infra-env:
    uv sync --quiet

# Stack secrets land on disk for the length of the call and no longer. No
# _infra-env here: `stack output` reads state, it doesn't run the program.
[working-directory('infra')]
_playbook +args:
    #!/usr/bin/env bash
    set -euo pipefail
    vars=$(mktemp)  # 0600
    trap 'rm -f "$vars"' EXIT
    pulumi stack output --json --show-secrets --stack prod >"$vars"
    cd ansible
    uv run --group deploy ansible-playbook playbook.yml -e "@$vars" {{ args }}

# Deploy an exact image tag. Needs PULUMI_ACCESS_TOKEN; CI runs this same recipe.
deploy tag: (_playbook ("-e image_tag=" + tag))

# Move the box onto a tagged Tailscale identity. Expect it to fail: it drops the connection it runs over.
retag: (_playbook "--tags tailscale -e tailscale_retag=true")
