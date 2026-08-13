import os

# Both must be set before anything imports old_news or testcontainers.
# Piccolo's engine_finder() resolves PICCOLO_CONF by name at import time, and
# testcontainers reads its config at import. Ryuk bind-mounts the docker socket,
# which Docker Desktop on macOS refuses.
os.environ.setdefault("PICCOLO_CONF", "old_news.db.piccolo_conf")
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")
