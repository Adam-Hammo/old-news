---
name: migration
description:
  Add or change a table, column, index or constraint in old-news — the model, the generated Alembic
  revision, and the Postgres-specific parts autogenerate cannot see. Use whenever a change touches
  src/old_news/db/models/ or db/migrations/.
---

# A schema change

Migrations are generated, never written by hand. The order matters: a step skipped here comes out as
an empty revision, silently.

## 1. The model

One module per model under `src/old_news/db/models/`, then two exports:

- the name in `db/models/__init__.py`. `migrations/env.py` imports that module and nothing else, so
  an unexported model registers no mapper and autogenerate produces an empty revision.
- the name in `db/__init__.py`, import block and `__all__` both, if anything outside `db/` uses it.
  A unit test asserts the second list covers the first, so a half-done export fails fast.

Patterns that are the normal way of working here, not workarounds:

- Primary keys come from the `UUIDPrimaryKey` mixin in `db/base.py` —
  `server_default=text("uuidv7()")`, so a row inserted by anything but this ORM still gets a key.
  Needs Postgres 18; the image is 18.4.
- A closed set of values is a `StrEnum`, a `Mapped[str]` column, and a check constraint from
  `db.base.one_of(column, TheEnum)`. Never `sa.Enum`, in either mode — the docstring on `one_of`
  says why.
- Constraint names come from `NAMING_CONVENTION` in `db/base.py`. The `ck` template interpolates the
  name you pass, so give it the bare suffix.
- Postgres indexes the referenced side of a foreign key, never the referencing one. Add the index if
  a query needs it — and not if a unique constraint's leading column already answers it.
- A counter, a last-error or a flag beside the log that produces it is a second copy that can only
  disagree. Derive it instead: `db.base.run_of` builds the "unbroken run at the tail of an
  append-only log" as SQL, which is what `Feed.consecutive_failures` and `Host.capture_failures`
  are. A `hybrid_property` whose Python half raises is the honest shape when the answer only exists
  in SQL.

## 2. Generate it

Autogenerate diffs the models against a live database, so Postgres has to be up.

```sh
just up                        # Docker; also applies what is already committed
just migration "what changed"
```

## 3. Read what came out

Always. Autogenerate is a first draft.

- `env.py` filters `procrastinate_*` out, because procrastinate migrates its own schema. A revision
  opening with a dozen `drop_table` calls means that filter stopped working, not that the schema
  moved.
- A partial index has a SQLAlchemy spelling — `postgresql_where=sa.text(...)` — and autogenerate
  emits it. `op.execute` is for what has none: backfilling a column you just added, and seed rows.
  The re-encode revision and the two seeded `training_rules` are the worked examples.
- Adding a value to an enum's check constraint drops and re-adds it. That cannot share a transaction
  with rows written using the new value.
- `alembic_utils` is installed and deliberately unwired. Read the paragraph on it in
  `docs/ARCHITECTURE.md` before registering anything with it.
- Migrations run on psycopg, not asyncpg, and the revision's docstring is where the reasoning for
  the change belongs — that is the one place in the tree where long prose is wanted.

## 4. Apply and check

```sh
just migrate           # applies Alembic, then procrastinate's own schema
just migration-status  # current revision, and what is pending
uv run alembic check   # fails if the models and the migrations have drifted apart
```

`alembic check` is the one that catches a model edited without a revision. `just rollback` steps
back if the revision was wrong.

An applied revision is history: never edit one that has run anywhere. Add another.
