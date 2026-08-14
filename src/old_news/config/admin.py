import secrets

from pydantic import BaseModel, Field, SecretStr

# Used only when no hash is configured, and never outside local development.
DEVELOPMENT_PASSWORD = "admin"


class AdminSettings(BaseModel):
    """Single user, seeded credentials. There is no registration endpoint."""

    enabled: bool = True
    path: str = "/admin"
    username: str = "admin"

    # A scrypt hash from `just admin-password`, not a password. Empty means
    # unconfigured: development falls back to DEVELOPMENT_PASSWORD, production
    # refuses to start.
    password_hash: SecretStr = SecretStr("")

    # Regenerated per process when unset, which logs every session out on
    # restart — the right default for something that must never be public.
    session_secret: SecretStr = Field(default_factory=lambda: SecretStr(secrets.token_urlsafe(32)))

    @property
    def configured(self) -> bool:
        return bool(self.password_hash.get_secret_value())
