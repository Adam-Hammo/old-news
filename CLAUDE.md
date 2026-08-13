# Style

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how the code is laid out and why.

- `uv` for everything. Never call `python`, `pip`, `pytest` or `ruff` directly.
- No `from __future__ import annotations`.
- Comment sparingly: non-obvious logic only, never a restatement of the code. No references to
  documentation files — if something needs explaining at length, it belongs in `docs/`.
- Prefer a new package over growing a module past a few hundred lines.
- Library imports stay in one module. `httpx2` belongs to `fetch/`, `logfire` to `observability/`.
- Services hold the logic. Routes and tasks stay thin enough to read in one screen.
- Tests go in `tests/unit/` if they need nothing external, `tests/integration/` otherwise, mirroring
  the `src/` path.
- Don't mock Postgres or HTTP. Use the real thing.
- Formatting and linting are pre-commit's job. Run `just check` before calling anything done.
