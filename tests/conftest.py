import os

# Ryuk bind-mounts the docker socket, which Docker Desktop on macOS refuses.
# testcontainers reads its config at import, so this must run first.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")
