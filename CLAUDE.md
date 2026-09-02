# old-news

## Style

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how the code is laid out and why.

- `uv` for everything. Never call `python`, `pip`, `pytest` or `ruff` directly.
- No `from __future__ import annotations`.
- Comment sparingly. Good code is readable without prose, so a comment is a claim that this bit is
  not. One-line docstrings stating intention; comments only where the mechanism is genuinely obscure
  and getting it wrong is easy. Never restate the code, never narrate the design, and never reach
  for a named example from the corpus to make a point. Rationale belongs in the commit message;
  anything longer belongs in `docs/`, which the code does not reference.
  `tests/unit/test_architecture.py` ratchets all of this — the budgets only go down, and raising one
  is the argument you have to make out loud.
- Prefer a new package over growing a module past a few hundred lines. But a _new top-level_ package
  is a decision to state out loud: if `docs/ROADMAP.md` calls something "the same mechanism" as an
  existing thing, extend that thing instead of adding a sibling. Scope where the code belongs before
  writing it, not after.
- One function, one transaction. Postgres writes go in a `@db.transactional` function that takes the
  session first; anything else — a fetch, parsing a large body — stays in the caller. Transactions
  don't nest and `db.session()` will refuse to.
- Library imports stay in one package, often one module. `httpx2` belongs to `fetch/`, `logfire` to
  `observability/`; `per-file-ignores` in pyproject.toml is the list of owners.
- Services hold the logic. Routes and tasks stay thin enough to read in one screen.
- Tests go in `tests/unit/` if they need nothing external, `tests/integration/` otherwise, mirroring
  the `src/` path.
- Don't mock Postgres or HTTP. Use the real thing.
- Formatting and linting are pre-commit's job. Run `just check` before calling anything done.
- No dead code. `vulture` runs in pre-commit; `just dead` on its own. If a framework needs a name
  you never read, add it to `[tool.vulture]` in pyproject.toml or prefix the parameter with `_`.

## Working

- `just quick` after every edit: ruff, ty, vulture and `tests/unit`, ten seconds and no Docker.
  `just check` before calling anything done — it adds the integration suite and the client's, so it
  needs Docker up, and the first run builds the Postgres image.
- One test is `just test unit -k cursor`, or a path: `just test unit/ui/test_cursor.py`.
- Every run draws its own data seed and prints it twice on a red one. Replay with
  `OLD_NEWS_TEST_SEED=… just test` before assuming your change is at fault. `just sweep` draws
  several on purpose.
- `web/` is the other toolchain — `npm --prefix web`, never `uv` — and none of the rules above are
  about it. `web/README.md` has its conventions.
- Generated, so never hand-edited: `web/src/lib/api/schema.d.ts` (`just web-types`, needs the API
  running), `db/migrations/versions/*` (`just migration`), `uv.lock`, `infra/sdks/`. The `exclude`
  at the top of `.pre-commit-config.yaml` is the list.
- A new third-party library is two edits in pyproject.toml: a `banned-api` entry naming its owner
  and a `per-file-ignores` entry for that owner. Never a `# noqa: TID251`.
- A new settings section is a `BaseModel` — not `BaseSettings` — in `config/<name>.py`, a field on
  `Settings`, and the name in `config/__init__.py`'s `__all__`.
- A new task is a module in `tasks/`, named in `import_paths` in `tasks/app.py` or nothing registers
  it. Something else defers it: `@task(app, …)` from `tasks.tracing`, so the traceparent survives. A
  cron defers it: `@app.periodic` over `@app.task`. Its queue goes in `WorkerSettings.concurrency`.
  A sweep that defers one job per due row belongs in `tasks/sweep.py`, not written again.
- Two workflows have skills, because both have more traps than you will read for: `.claude/skills/`
  covers a schema change and a route plus the client contract that moves with it.

## Docs

`docs/ARCHITECTURE.md` is the one the rules point at. The others answer narrower questions:
`ROADMAP.md` what is planned and what it is "the same mechanism" as, `PHASE-1/2/3.md` what got built
and why that way, `SCOPE-feed-capture.md` one decomposition in full. The phase documents are
history, not plans — they describe work already delivered.
