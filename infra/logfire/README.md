# logfire

`dashboards/*.json` is picked up by `telemetry_logfire.py` and applied by `just infra-up`, one
`logfire.Dashboard` per file. The slug is the filename; the display name comes from
`spec.display.name` inside the file.

| Dashboard             | Panels                                                                                          |
| --------------------- | ----------------------------------------------------------------------------------------------- |
| `ingest-health.json`  | poll outcomes, HTTP status mix, slowest feeds, feeds failing most, suspended feeds              |
| `queue-and-host.json` | queue depth, task duration, job outcomes by task, recent task failures, host CPU/memory, timers |

## The definition format

Confirmed against a real export of the standard **Usage Overview** dashboard:

| Piece           | Value                                                                           |
| --------------- | ------------------------------------------------------------------------------- |
| Envelope        | `kind: Dashboard`, `metadata: {name, project}`, `spec`                          |
| Panel           | `kind: Panel`, `spec: {display, plugin, queries}`                               |
| Table panel     | `plugin.kind: "Table"`, `spec: {query: ""}`                                     |
| Non-time-series | `query.kind: "NonTimeSeriesQuery"` → `plugin.kind: "LogfireNonTimeSeriesQuery"` |
| Query spec      | `{query, groupBy, metrics}`                                                     |
| Layout          | `kind: Grid`, items `{x, y, width, height, content: {$ref}}` on 24 columns      |
| `$resolution`   | a hidden `TextVariable` named `resolution`, e.g. `"1 minute"`                   |

**`TimeSeries` and `LogfireTimeSeriesQuery` are inferred, not confirmed.** The export contained only
`Table` panels, and the API types plugin kinds as free-form — a wrong one is accepted on write and
renders an empty panel. If a time series panel comes up blank, those two strings are the only thing
to fix. Exporting any dashboard that has a time series panel settles it.

Editing the SQL in a committed file is always safe; only the plugin kinds have to come from a real
export. To add a dashboard: build it in the UI, **Download dashboard as code**, drop the file here —
then delete `spec.annotations` and `spec.links` and add `spec.datasources: {}`. The UI exports keys
the API discards on read, and the mismatch makes every plan propose an update.

## What the queries assume

Columns come from Logfire's own schema — `span_name`, `service_name`, `level`, `duration`,
`attributes->>'...'`, `otel_status_message` on `records`; `metric_name`, `scalar_value`,
`recorded_timestamp` on `metrics`. `records_all` is the unsampled variant, used for volume counting
rather than for anything here.

The metric and span names are this project's: `ingest.*` and `queue.*` from `observability`, the
`poll feed` / `GET feed` / `task <name>` spans, and `service_name = 'old-news-host'` for the systemd
reporter in `ansible/roles/otel`. Renaming any of those breaks a panel silently.
