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

[working-directory('infra')]
tf-preview:
    uv run --group infra pulumi preview

[working-directory('infra')]
tf-up:
    uv run --group infra pulumi up

[working-directory('infra')]
provision:
    uv run --group infra ansible-playbook -i ansible/inventory.ini ansible/playbook.yml
