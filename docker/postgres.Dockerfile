# pg_search comes from ParadeDB's extension-only OCI artifact rather than their full
# image, which bootstraps PostGIS, pg_ivm and pg_cron into template1 and your database.
FROM paradedb/paradedb-extension:0.25.10-18-trixie AS pg_search
# From an image rather than apt, so the version is pinned and Dependabot moves it.
FROM pgvector/pgvector:0.8.6-pg18-trixie AS pgvector

FROM postgres:18.4-trixie

ARG PGVECTORSCALE_VERSION=0.9.0
ARG TARGETARCH

# curl is for initdb/00-tune.sh, which fetches tuning from api.pgconfig.org.
# hadolint ignore=DL3008
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates unzip \
 && rm -rf /var/lib/apt/lists/*

COPY --from=pgvector /usr/lib/postgresql/18/lib/vector.so /usr/lib/postgresql/18/lib/
COPY --from=pgvector /usr/lib/postgresql/18/lib/bitcode/vector /usr/lib/postgresql/18/lib/bitcode/vector
COPY --from=pgvector /usr/lib/postgresql/18/lib/bitcode/vector.index.bc /usr/lib/postgresql/18/lib/bitcode/
COPY --from=pgvector /usr/share/postgresql/18/extension/vector* /usr/share/postgresql/18/extension/

COPY --from=pg_search /lib/pg_search.so /usr/lib/postgresql/18/lib/
COPY --from=pg_search /share/extension/ /usr/share/postgresql/18/extension/
# pg_search links against openblas/gfortran, which the artifact carries.
COPY --from=pg_search /system/ /usr/lib/postgresql/18/lib/
RUN echo /usr/lib/postgresql/18/lib > /etc/ld.so.conf.d/pg_search.conf && ldconfig

# pgvectorscale ships .deb files inside a zip. StreamingDiskANN only earns its
# keep at millions of vectors, but adding it later means a reindex either way.
RUN curl -fsSL -o /tmp/pgvectorscale.zip \
      "https://github.com/timescale/pgvectorscale/releases/download/${PGVECTORSCALE_VERSION}/pgvectorscale-${PGVECTORSCALE_VERSION}-pg18-${TARGETARCH}.zip" \
 && unzip -j /tmp/pgvectorscale.zip -d /tmp/pgvectorscale \
 && apt-get install -y --no-install-recommends \
      "/tmp/pgvectorscale/pgvectorscale-postgresql-18_${PGVECTORSCALE_VERSION}-Linux_${TARGETARCH}.deb" \
 && rm -rf /tmp/pgvectorscale /tmp/pgvectorscale.zip /var/lib/apt/lists/*

COPY initdb/ /docker-entrypoint-initdb.d/
