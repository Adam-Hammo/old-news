---
name: api-route
description:
  Add or change an HTTP endpoint in old-news and keep the SvelteKit client's generated types in
  step. Use whenever a change touches src/old_news/api/routes/ or web/src/lib/api/.
---

# A route, and the contract it moves

`api/` is an adapter: it parses input, calls a service and shapes a response. The rule belongs in
the feature package's `service.py`. A route holding one is what this layout exists to prevent.

## The route

One module per surface under `src/old_news/api/routes/`, ending in a router factory:

```python
def reading_router(path: str = "/") -> Router:
    return Router(path=path, route_handlers=[river, article], tags=["reading"])
```

Then three registrations:

- the factory in `api/routes/__init__.py`, import and `__all__` both
- a call to it in `create_app`'s `handlers` list in `api/app.py`. A router not in that list is not
  served, and nothing anywhere says so.
- `summary=` on every handler. It is what the OpenAPI schema shows and the client reads.

Response types are frozen slotted dataclasses — beside the handler if the shape is the route's own,
returned by the service if it is the service's. Litestar builds the schema from the return
annotation, so a `dict` return produces a contract the client cannot use.

A service raising its own error becomes an HTTP status here and nowhere else: catch it in the
handler and re-raise Litestar's, the way `river` turns `ui.BadCursor` into a `ClientException`.

## The client's half

Generated, not written:

```sh
just serve      # in another shell — the API on :16051
just web-types  # rewrites web/src/lib/api/schema.d.ts from /schema
just web-check  # does the client still type-check against the new contract
```

Never edit `schema.d.ts`, and never reach for a field in `web/src/lib/api/client.ts` that is not in
it — regenerate instead. `just web-build` is the same check CI runs.

## The test

`tests/integration/api/test_<surface>.py`. Two fixtures, and the wrong one is a 500:

- `client` — the app over whatever the database already holds. Right for a request that needs no
  rows: a rejected parameter, a forged cursor, a 404.
- `served` — the app over an empty archive, awaited _after_ the rows are written. `AsyncTestClient`
  runs the app on an event loop of its own and asyncpg binds a connection to the loop that opened
  it, so the pool the test filled has to be disposed before the app reads. `served` does that.

```python
async def test_the_river_serialises_a_row_whole(served, feed, story):
    await story(await feed("outlet.example.com", category="Technology"), "A headline", body="Text.")

    response = await (await served()).get("/river")

    assert response.json()["entries"][0]["title"] == "A headline"
```

`feed` and `story` build rows directly, in `tests/integration/conftest.py` — a poll is not what a
reading screen is about.
