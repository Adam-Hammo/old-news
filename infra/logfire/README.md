# logfire

`dashboards/*.json` is picked up by `telemetry_logfire.py` and applied by `just infra-up`, one
`logfire.Dashboard` per file. The slug is the filename; the display name comes from
`spec.display.name` inside the file.

| Dashboard             | Panels                                                                                        |
| --------------------- | --------------------------------------------------------------------------------------------- |
| `ingest-health.json`  | poll outcomes, poll duration, HTTP status mix, slowest feeds, feeds failing most, suspensions |
| `queue-and-host.json` | queue depth, task duration and outcomes, host CPU/memory/disk/load, container health, timers  |
| `backup.json`         | snapshot and repository size, snapshots kept, backup runs — on a 30-day window                |

## The definition format

Confirmed against real exports of the standard **PostgreSQL**, **Web Server Metrics** and **Basic
System Metrics** dashboards:

| Piece        | Value                                                                 |
| ------------ | --------------------------------------------------------------------- |
| Envelope     | `kind: Dashboard`, `metadata: {name, project}`, `spec`                |
| Panel        | `kind: Panel`, `spec: {display, plugin, queries}`                     |
| Panel kinds  | `Table`, `TimeSeriesChart`, `BarChart`, `GaugeChart`, `Values`        |
| Table panel  | `plugin.spec: {query: ""}` — the SQL lives in `queries`, not here     |
| Time series  | `plugin.spec: {legend, yAxis, visual}`                                |
| Series query | `TimeSeriesQuery` → `LogfireTimeSeriesQuery`                          |
| Table query  | `NonTimeSeriesQuery` → `LogfireNonTimeSeriesQuery`                    |
| Query spec   | `{query, groupBy, metrics}`; a table query takes `{query}` alone      |
| Layout       | `kind: Grid`, items `{x, y, width, height, content: {$ref}}`, 24 cols |
| $resolution  | supplied by Logfire from the range — do **not** declare a variable    |

Two of these cost a deploy each to learn, so they are worth stating plainly:

`groupBy` names the column holding the series label and `metrics` names the value column(s). Both
empty renders an empty chart no matter how good the SQL is — a time series panel needs to be told
which column is which. Multiple value columns are allowed, and then `groupBy` is `""`.

Declaring a `resolution` variable shadows Logfire's own and freezes every bucket at whatever it is
pinned to. The standard dashboards use `$resolution` and declare nothing.

A wrong plugin kind is accepted on write and renders an empty panel, so a blank chart is a format
bug rather than a data bug until proven otherwise. To add a dashboard: build it in the UI,
**Download dashboard as code**, drop the file here — then delete `spec.annotations` and `spec.links`
and add `spec.datasources: {}`. The UI exports keys the API discards on read, and the mismatch makes
every plan propose an update.

## What the queries assume

On `records`: `span_name`, `service_name`, `level`, `duration` (seconds), `start_timestamp`,
`otel_status_message`, `attributes->>'...'`. `records_all` is the unsampled variant, used for volume
counting rather than for anything here.

On `metrics`: `metric_name`, `recorded_timestamp`, `attributes->>'...'` for data point attributes
and `otel_resource_attributes->>'...'` for resource ones. Read values through the helpers —
`metric_sum`, `metric_avg`, `metric_rate`, `metric_delta`, `metric_count`, `metric_quantile` —
rather than the raw `scalar_value` column. The app's own counters are delta and sum correctly either
way, but everything from the collector is cumulative, where summing raw values is meaningless.

`AND recorded_timestamp < time_bucket($resolution, now())` drops the partial current bucket, which
otherwise draws every series falling off a cliff at the right edge. It belongs on anything sampled
faster than the bucket and nowhere else: `backup.*` arrives once a day, so on a 30-day window the
guard hid the newest point — the whole series, until there were two of them. Sparse metrics get no
guard, because a bucket holding one sample is not partial.

The metric and span names are this project's: `ingest.*` and `queue.*` from `observability`, the
`poll feed` / `GET feed` / `task <name>` spans, and `service_name = 'old-news-host'` for the systemd
reporter in `ansible/roles/otel`. Renaming any of those breaks a panel silently.

## Host metrics come from the collector, not the app

`docker/otel-collector.yaml` is the source for everything `system.*`, `container.*` and
`postgresql.*`. Two things about it decide whether these dashboards have data at all.

The `utilization` metrics are opt-in. By default the scrapers emit `system.cpu.time` and
`system.memory.usage` and nothing else, so every percentage panel comes up blank. Same for a good
half of the PostgreSQL receiver's metrics — Logfire's own PostgreSQL dashboard marks exactly those
panels `needs-setup`.

Logfire's **Basic System Metrics (OpenTelemetry)** dashboard is written for the Python SDK's
psutil-based metrics, not for collector hostmetrics: it keys off `process_pid`, the `available`
memory state, and `process.runtime.*`, none of which the collector emits. Its CPU panel works; the
rest of it will not, and that is not worth chasing — `queue-and-host.json` covers the same ground
against the metrics we actually have.

## Where the backup numbers come from

`docker/backup/report` runs at the end of `docker/backup/backup` and POSTs restic's own figures to
`/v1/metrics` as `backup.*`, the same way `ansible/roles/otel` reports systemd units to `/v1/logs`.
It is deliberately unable to fail a backup: no token, no `jq`, or an unreachable endpoint all exit
0, which is also what keeps `just backup` from reporting a laptop. Each of those says so on the way
out, so `journalctl -u old-news-backup` is where a blank panel gets answered.

`backup.snapshot.size` is restic's `restore-size` — the dump as `pg_restore` would read it.
`backup.repository.size` is `raw-data`, what the bucket holds after dedup and compression, and
therefore what Backblaze bills. There is no B2-side metric worth collecting on top of that: restic
already knows the number, and the alternative is polling an API for something we can read locally.
