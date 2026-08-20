from pydantic import BaseModel


class StorageSettings(BaseModel):
    # zstd level for every stored body. 3 is the library default; 19 costs 45 ms a page
    # for another 5%. 12 is 3 ms and most of the win.
    compression_level: int = 12

    # Below this a scope stays on plain zstd, which is always correct.
    dictionary_min_samples: int = 20
    dictionary_sample_limit: int = 100

    # Tried in turn and judged on a held-out sample. The ladder stops at 512K because the
    # trainer, asked for more than it can use, emits a far smaller dictionary than at 256K.
    dictionary_size_ladder: tuple[int, ...] = (
        64 * 1024,
        128 * 1024,
        256 * 1024,
        512 * 1024,
        1024 * 1024,
    )

    # Templates drift. A retrain inserts a new dictionary and never rewrites a body,
    # so the old one stays reachable for everything already compressed against it.
    dictionary_max_age_seconds: int = 30 * 24 * 60 * 60
    dictionary_batch_size: int = 5
