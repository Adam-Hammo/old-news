# pg_dump and restic in one place, so backup and restore are the same code path
# locally and on the host. Same Postgres major as the server — pg_dump refuses to
# dump a newer server than itself.
FROM postgres:18.4-trixie

# curl and jq are for `report` — restic's numbers become OTLP metrics.
# hadolint ignore=DL3008
RUN apt-get update \
 && apt-get install -y --no-install-recommends restic ca-certificates curl jq \
 && rm -rf /var/lib/apt/lists/*

COPY backup/ /usr/local/bin/
RUN chmod +x /usr/local/bin/backup /usr/local/bin/restore /usr/local/bin/verify-restore \
      /usr/local/bin/report

ENTRYPOINT []
CMD ["backup"]
