"""How stored bodies are compressed. The only module that imports zstd.

Postgres TOASTs `BYTEA` with pglz, which manages about 2x on feed XML. Plain zstd
gets 6-7x, and a trained dictionary doubles that again on documents from one feed,
which are near-identical poll to poll. Bodies are the great majority of the database.
"""

from compression import zstd

# Bodies stored before compression began start with `<` or a BOM, never with this,
# so both read the same way and nothing needs migrating.
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"

# What a frame header carries when no dictionary was used.
NO_DICTIONARY = 0


def compress(body: bytes, *, level: int, dictionary: zstd.ZstdDict | None = None) -> bytes:
    """The level is passed rather than defaulted: two places deciding it is one too many."""
    return zstd.compress(body, level, zstd_dict=dictionary)


def dictionary_id(body: bytes) -> int:
    """Which dictionary this body needs, or `NO_DICTIONARY` if it needs none.

    A zstd frame names its own dictionary, so a body is self-describing and reading
    one never depends on remembering what compressed it.
    """
    if not body.startswith(ZSTD_MAGIC):
        return NO_DICTIONARY
    return zstd.get_frame_info(body).dictionary_id


def decompress(body: bytes, dictionary: zstd.ZstdDict | None = None) -> bytes:
    """The way back. Uncompressed bodies pass through untouched.

    A dictionary is only handed over when the frame asks for one: zstd rejects a
    dictionary a frame was not compressed with, rather than quietly guessing.
    """
    if not body.startswith(ZSTD_MAGIC):
        return body
    if dictionary is None:
        return zstd.decompress(body)
    return zstd.decompress(body, zstd_dict=dictionary)
