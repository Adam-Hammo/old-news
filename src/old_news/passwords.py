"""Password hashing for the admin UI. stdlib scrypt — no dependency, no service.

Hashed so the copies that end up in `.env`, stack outputs and the box's environment
are unusable, not because the UI is exposed.
"""

import base64
import secrets
from hashlib import scrypt
from hmac import compare_digest

SCHEME = "scrypt"
# Not "$": compose expands $NAME in an env value, which would eat the salt.
# Base64 never produces a colon.
SEPARATOR = ":"
COST = 2**15
BLOCK_SIZE = 8
PARALLELISM = 1
SALT_BYTES = 16
KEY_BYTES = 32
FIELDS = 6


def _encode(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def _derive(password: str, salt: bytes, *, cost: int, block: int, parallel: int) -> bytes:
    return scrypt(
        password.encode(),
        salt=salt,
        n=cost,
        r=block,
        p=parallel,
        maxmem=cost * block * 256,
        dklen=KEY_BYTES,
    )


def hash_password(password: str) -> str:
    """`scrypt:cost:block:parallel:salt:key`, salt and key base64."""
    salt = secrets.token_bytes(SALT_BYTES)
    key = _derive(password, salt, cost=COST, block=BLOCK_SIZE, parallel=PARALLELISM)
    return SEPARATOR.join(
        [SCHEME, str(COST), str(BLOCK_SIZE), str(PARALLELISM), _encode(salt), _encode(key)]
    )


def verify(password: str, encoded: str) -> bool:
    """Parameters come from the stored hash, so raising COST keeps old hashes valid."""
    parts = encoded.split(SEPARATOR)
    if len(parts) != FIELDS or parts[0] != SCHEME:
        return False

    try:
        cost, block, parallel = (int(part) for part in parts[1:4])
        salt, expected = base64.b64decode(parts[4]), base64.b64decode(parts[5])
    except ValueError:
        return False

    try:
        candidate = _derive(password, salt, cost=cost, block=block, parallel=parallel)
    except ValueError:
        return False
    return compare_digest(candidate, expected)
