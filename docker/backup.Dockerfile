# pg_dump and restic in one place, so backup and restore are the same code path
# locally and on the host. Same Postgres major as the server — pg_dump refuses to
# dump a newer server than itself.
FROM postgres:18.4-trixie

# hadolint ignore=DL3008
RUN apt-get update \
 && apt-get install -y --no-install-recommends restic ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY backup/ /usr/local/bin/
RUN chmod +x /usr/local/bin/backup /usr/local/bin/restore /usr/local/bin/verify-restore

ENTRYPOINT []
CMD ["backup"]
