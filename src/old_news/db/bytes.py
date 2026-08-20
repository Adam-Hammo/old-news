"""How stored bodies are compressed. The only module that imports zstd."""

from compression import zstd

# Bodies stored before compression began never start with this, so both read the same way.
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"

# What a frame header carries when no dictionary was used.
NO_DICTIONARY = 0


def compress(body: bytes, *, level: int, dictionary: zstd.ZstdDict | None = None) -> bytes:
    """Compress a body. The level is passed rather than defaulted."""
    return zstd.compress(body, level, zstd_dict=dictionary)


def dictionary_id(body: bytes) -> int:
    """Which dictionary this body needs, read off the frame, or `NO_DICTIONARY`."""
    if not body.startswith(ZSTD_MAGIC):
        return NO_DICTIONARY
    return zstd.get_frame_info(body).dictionary_id


def decompress(body: bytes, dictionary: zstd.ZstdDict | None = None) -> bytes:
    """The way back. Uncompressed bodies pass through, and zstd rejects a wrong dictionary."""
    if not body.startswith(ZSTD_MAGIC):
        return body
    if dictionary is None:
        return zstd.decompress(body)
    return zstd.decompress(body, zstd_dict=dictionary)
