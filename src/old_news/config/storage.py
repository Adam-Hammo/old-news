from pydantic import BaseModel


class StorageSettings(BaseModel):
    # zstd level for every stored body. 3 is the library default; 19 costs 45 ms a page
    # for another 5%. 12 is 3 ms and most of the win.
    compression_level: int = 12

    # A dictionary needs something to learn from, and how much is what decides whether it
    # is any good — measured on real pages, eight samples buys 16% and twenty-eight buys
    # 50%. Below the floor a scope stays on plain zstd, which is always correct and is what
    # every body starts out as.
    dictionary_min_samples: int = 20
    dictionary_sample_limit: int = 100

    # Candidate dictionary sizes, tried in turn and judged on a held-out sample, because the
    # best one is a property of the scope rather than a constant.
    #
    # The ladder stops at 512K because the trainer has a cliff: asked for much more than it
    # can use it emits a far *smaller* dictionary than it would have at 256K, which is worse
    # than either. Judging each candidate rather than trusting the number sidesteps that.
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
