# docker-library/python publishes no free-threaded tags (issue #1082), so the
# interpreter comes from uv — which is the recommended way to get one anyway.
# .python-version pins it; bump there, not here.
FROM debian:trixie-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/opt/python

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=.python-version,target=.python-version \
    uv python install

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=.python-version,target=.python-version \
    uv sync --locked --no-install-project --no-dev

COPY pyproject.toml uv.lock README.md .python-version ./
COPY src/ ./src/

RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev


# The converter, fetched and stripped here so neither the download tools nor the
# parts of calibre a headless EPUB conversion never touches reach the image.
FROM debian:trixie-slim AS calibre

ARG CALIBRE_VERSION=8.16.0
ARG TARGETARCH

# hadolint ignore=DL3008,DL3047
RUN apt-get update \
 && apt-get install -y --no-install-recommends wget xz-utils ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && arch="$(case "${TARGETARCH:-amd64}" in arm64) echo arm64 ;; *) echo x86_64 ;; esac)" \
 && wget -qO /tmp/calibre.txz \
      "https://download.calibre-ebook.com/${CALIBRE_VERSION}/calibre-${CALIBRE_VERSION}-${arch}.txz" \
 && mkdir -p /opt/calibre \
 && tar xJof /tmp/calibre.txz -C /opt/calibre \
 && rm /tmp/calibre.txz

# WebEngine is PDF output and the viewer; onnxruntime is speech; the av* libraries are
# audiobooks. None of them is on the path from markdown to an EPUB.
RUN rm -rf /opt/calibre/translations \
 && rm -f /opt/calibre/lib/libQt6WebEngine*.so.6 \
          /opt/calibre/lib/libQt6Pdf*.so.6 \
          /opt/calibre/lib/libonnxruntime.so.1 \
          /opt/calibre/lib/libav*.so.* \
          /opt/calibre/lib/libsw*.so.* \
          /opt/calibre/bin/QtWebEngineProcess \
 && rm -rf /opt/calibre/resources/qtwebengine_*


FROM debian:trixie-slim

# libpq5 because psycopg is the pure-python build — psycopg-binary ships no
# free-threaded wheels, and pure psycopg loads libpq at runtime. The rest is what
# calibre's bundled Qt links against — read off `ldd`, not guessed, because the
# packages a desktop calibre wants are mostly for the GUI it never starts here.
# `fonts-liberation` is what the generic `serif` resolves to; with no system font at
# all the converter sets the plates in whatever it can find.
# hadolint ignore=DL3008
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libpq5 ca-certificates \
      libegl1 libopengl0 libglx0 libxkbcommon0 \
      libfontconfig1 libfreetype6 libdbus-1-3 \
      fonts-liberation \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --create-home app

COPY --from=calibre /opt/calibre /opt/calibre
COPY --from=builder --chown=app:app /opt/python /opt/python
COPY --from=builder --chown=app:app /app /app

# Calibre insists on a writable config directory, and the container is read-only
# everywhere but /tmp, which compose mounts as tmpfs.
ENV PATH="/app/.venv/bin:/opt/calibre:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    QT_QPA_PLATFORM=offscreen \
    CALIBRE_CONFIG_DIRECTORY=/tmp/calibre \
    CALIBRE_TEMP_DIR=/tmp \
    XDG_CACHE_HOME=/tmp \
    LANG=C.UTF-8

WORKDIR /app
USER 10001
EXPOSE 8000

CMD ["python", "-m", "old_news", "serve"]
