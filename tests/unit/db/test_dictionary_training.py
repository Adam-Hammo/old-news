"""Training is pure, so the interesting cases need no database."""

from compression import zstd

from old_news.config import StorageSettings
from old_news.db import bytes as codec
from old_news.db import dictionaries


def _documents(count: int) -> list[bytes]:
    """Feed documents differ a little and repeat a lot, which is the point."""
    return [
        f'<?xml version="1.0"?><rss><channel><title>Loopback News</title>'
        f"<item><guid>{n}</guid><description>story {n}</description></item>"
        "</channel></rss>".encode()
        * 40
        for n in range(count)
    ]


def test_too_few_samples_trains_nothing():
    """A scope with little to learn from stays on plain zstd, which always reads."""
    settings = StorageSettings(dictionary_min_samples=20)

    assert dictionaries.train(_documents(19), settings) is None


def test_the_floor_beats_a_configured_minimum_below_it():
    """zstd's trainer refuses a handful of samples whatever it is asked for, so a
    configuration that would crash it has to be impossible rather than handled."""
    settings = StorageSettings(dictionary_min_samples=2)

    assert dictionaries.train(_documents(dictionaries.MIN_TRAINABLE_SAMPLES - 1), settings) is None
    assert dictionaries.train(_documents(dictionaries.MIN_TRAINABLE_SAMPLES), settings) is not None


def test_training_records_what_it_learned_from():
    """One sample short of what it was given: the first is held out to judge the candidate
    sizes against, so it is not part of what the dictionary learned."""
    settings = StorageSettings(dictionary_min_samples=10)
    samples = _documents(10)

    trained = dictionaries.train(samples, settings)

    assert trained is not None
    assert trained.dict_id != codec.NO_DICTIONARY
    assert trained.sample_count == len(samples) - 1
    assert trained.sample_bytes == sum(len(sample) for sample in samples[1:])


def test_a_dictionary_beats_plain_zstd_on_what_it_was_trained_on():
    """The whole justification. Held-out sample, so this is not measuring memorisation."""
    settings = StorageSettings(dictionary_min_samples=10)
    samples = _documents(20)
    held_out = samples[0]

    trained = dictionaries.train(samples[1:], settings)
    assert trained is not None
    loaded = zstd.ZstdDict(trained.body)

    level = settings.compression_level
    assert len(codec.compress(held_out, level=level, dictionary=loaded)) < len(
        codec.compress(held_out, level=level)
    )
