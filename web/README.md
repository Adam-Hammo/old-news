# web

The reading UI. A SvelteKit client against the JSON API, and a sibling of `src/` rather than a
package inside it — different language, different conventions, and the rules in the repo's
`CLAUDE.md` are about Python. The reasoning is in `docs/PHASE-3.md`; the boundary is in
`docs/ARCHITECTURE.md`.

## Running it

```sh
just serve      # the API on :16051
just web-dev    # vite on :16053, proxying /api to it
```

Or `just up`, which runs the whole stack in compose and puts the client on :16052.

The proxy strips `/api` before forwarding, which is exactly what `tailscale serve --set-path=/api`
does in front of the deployment. So the client only ever knows a prefix, never a host, and the same
code runs in both places.

## Checks

Four, mirroring the four the Python side has: `prettier` formats, `eslint` lints, `svelte-check`
types, and `npm audit` watches the lockfile. All of them run as pre-commit hooks, so `just lint` is
the whole of it and `just check` adds the tests.

Tests come in two projects. Component tests run in a real browser through Playwright — the same
reason the Python suite will not mock Postgres — and everything else runs on node:

```sh
just web-test                     # both
just web-test --project node      # the fast half
just web-test --project browser
```

`src/design.test.ts` is the odd one out and the one worth knowing about. It asserts the design
system rather than any component: that no component paints a colour literal, that the root declares
`color-scheme: light dark`, and that no colour token is defined for only one of the two schemes — a
token missing from the dark block keeps its light value there and nobody notices for weeks.

## The contract is generated

Litestar publishes OpenAPI at `/schema`, and `just web-types` turns it into
`src/lib/api/schema.d.ts`. That file is committed and never edited by hand: it is the only thing
stopping the two languages drifting quietly, and regenerating it is how a change to a route arrives
here.

## How it is put together

Two screens and no navigation, because there is nowhere else to go.

The river is loaded by the **layout**, not by its route. On a wide screen the article renders beside
it, so the list cannot belong to the page the article replaces — and keeping one instance alive is
also what preserves the scroll position, which is the article's only way back.

Neither the river nor the article knows how wide the window is. Both are fluid and render the same
at 390px, 430px and 900px; what changes with width is the shell around them, so the media query
lives in exactly one file. Type inside each pane is sized against the pane, not the viewport.

`ssr = false`. The API is same-origin from the browser and nowhere else, so rendering on the server
would mean the node process calling back out through `tailscale serve` to reach Litestar.

## Style

Plain CSS. Every colour, face and rhythm is a custom property in `src/app.css`; components style
themselves with those and scope the rest, which is what lets the whole design follow the system's
light and dark setting from one pair of blocks. `src/design.test.ts` keeps it that way. No utility framework: this design is set by type and
rules, which is the thing utility classes are worst at. Faces are the platform's serif and sans
today — self-hosting is a drop-in at the two font tokens.

## The service worker

One job: a page instead of the browser's error when the app cannot be reached. It tells the two
failures apart — a 5xx means the host answered, so the tailnet is up and the app is not; a thrown
fetch means the tailnet is down — and says something different for each. Nothing else is cached and
no reading works offline.
