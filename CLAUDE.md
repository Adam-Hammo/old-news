# Style

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how the code is laid out and why.

- `uv` for everything. Never call `python`, `pip`, `pytest` or `ruff` directly.
- No `from __future__ import annotations`.
- Comment sparingly: non-obvious logic only, never a restatement of the code. No references to
  documentation files — if something needs explaining at length, it belongs in `docs/`.
- Prefer a new package over growing a module past a few hundred lines. But a _new top-level_ package
  is a decision to state out loud: if `docs/ROADMAP.md` calls something "the same mechanism" as an
  existing thing, extend that thing instead of adding a sibling. Scope where the code belongs before
  writing it, not after.
- One function, one transaction. Postgres writes go in a `@db.transactional` function that takes the
  session first; anything else — a fetch, parsing a large body — stays in the caller. Transactions
  don't nest and `db.session()` will refuse to.
- Library imports stay in one module. `httpx2` belongs to `fetch/`, `logfire` to `observability/`.
- Services hold the logic. Routes and tasks stay thin enough to read in one screen.
- Tests go in `tests/unit/` if they need nothing external, `tests/integration/` otherwise, mirroring
  the `src/` path.
- Don't mock Postgres or HTTP. Use the real thing.
- Formatting and linting are pre-commit's job. Run `just check` before calling anything done.
- No dead code. `vulture` runs in pre-commit; `just dead` on its own. If a framework needs a name
  you never read, add it to `[tool.vulture]` in pyproject.toml or prefix the parameter with `_`.
