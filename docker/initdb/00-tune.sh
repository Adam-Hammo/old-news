#!/usr/bin/env bash
# Postgres tuning comes from api.pgconfig.org, so the numbers are maintained by
# people who tune Postgres for a living rather than drifting every time someone
# edits this repo. The only inputs are the levers below.
#
#   PG_TUNING_ENVIRONMENT   WEB (default) | OLTP | DW | Mixed | Desktop
#   PG_TUNING_DRIVE_TYPE    SSD (default) | HDD | SAN
#   PG_TUNING_RAM_MB        detected from the container unless set
#   PG_TUNING_CPUS          detected from the container unless set
#   PG_TUNING_OFFLINE=1     skip the API; size two settings from RAM instead
#
# If the API can't be reached and offline mode wasn't asked for, initialisation
# fails. That is deliberate: a silently untuned database is worse than a loud stop.
set -euo pipefail

detect_ram_mb() {
  local bytes=""
  if [ -r /sys/fs/cgroup/memory.max ]; then
    bytes=$(cat /sys/fs/cgroup/memory.max)
    [ "$bytes" = "max" ] && bytes=""
  fi

  if [ -n "$bytes" ]; then
    echo $((bytes / 1024 / 1024))
  else
    awk '/MemTotal/ {print int($2 / 1024)}' /proc/meminfo
  fi
}

ram_mb=${PG_TUNING_RAM_MB:-$(detect_ram_mb)}
cpus=${PG_TUNING_CPUS:-$(nproc)}

if [ "${PG_TUNING_OFFLINE:-}" = "1" ]; then
  echo "WARNING: PG_TUNING_OFFLINE=1 — using fallback sizing, not api.pgconfig.org." >&2
  {
    echo
    echo "# old-news fallback sizing for ${ram_mb}MB — the API was not consulted."
    echo "shared_buffers = '$((ram_mb / 4))MB'"
    echo "effective_cache_size = '$((ram_mb * 3 / 4))MB'"
  } >>"$PGDATA/postgresql.conf"
  exit 0
fi

url="https://api.pgconfig.org/v1/tuning/get-config"
url+="?format=conf&pg_version=${PG_MAJOR}&total_ram=${ram_mb}MB&cpus=${cpus}"
url+="&environment_name=${PG_TUNING_ENVIRONMENT:-WEB}&drive_type=${PG_TUNING_DRIVE_TYPE:-SSD}"

echo "old-news: requesting tuning for ${ram_mb}MB / ${cpus} CPUs / pg${PG_MAJOR}"
conf=$(curl -fsS --max-time 20 --retry 3 --retry-delay 2 "$url") || conf=""

# The API answers 200 with an error body for bad input, so check the content
# rather than the status code.
if ! printf '%s' "$conf" | grep -q '^shared_buffers'; then
  echo "FATAL: no usable tuning from ${url}" >&2
  echo "       Set PG_TUNING_OFFLINE=1 to initialise without it." >&2
  exit 1
fi

printf '\n%s\n' "$conf" >>"$PGDATA/postgresql.conf"
printf '%s' "$conf" | grep -E '^(shared_buffers|effective_cache_size|work_mem) '
