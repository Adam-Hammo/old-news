from pydantic import BaseModel


class StorageSettings(BaseModel):
    # zstd level for every stored body. 3 is the library default; 19 costs 45 ms a page
    # for another 5%. 12 is 3 ms and most of the win.
    compression_level: int = 12

    # A dictionary needs something to learn from. Below this a scope stays on plain
    # zstd, which is always correct and is what every body starts out as.
    dictionary_min_samples: int = 20
    dictionary_sample_limit: int = 60
    dictionary_max_bytes: int = 110 * 1024

    # Templates drift. A retrain inserts a new dictionary and never rewrites a body,
    # so the old one stays reachable for everything already compressed against it.
    dictionary_max_age_seconds: int = 30 * 24 * 60 * 60
    dictionary_batch_size: int = 5
