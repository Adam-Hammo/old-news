"""Stored bodies are compressed, and the ones stored before that still read."""

from compression import zstd

import pytest

from old_news.config import StorageSettings
from old_news.db import bytes as codec

FEED = b'<?xml version="1.0"?><rss><channel><title>x</title></channel></rss>' * 200
PAGE = b"<html><head><title>x</title></head><body><p>words</p></body></html>" * 200

LEVEL = StorageSettings().compression_level


def test_a_compressed_body_reads_back_unchanged():
    assert codec.decompress(codec.compress(FEED, level=LEVEL)) == FEED


def test_an_uncompressed_body_is_returned_as_is():
    """No migration ran, so rows written before compression must still be readable."""
    assert codec.decompress(FEED) == FEED


def test_a_body_stored_at_the_old_level_still_reads():
    assert codec.decompress(zstd.compress(FEED, 3)) == FEED


def test_compression_is_worth_doing_on_feed_xml():
    assert len(codec.compress(FEED, level=LEVEL)) < len(FEED) / 4


def test_a_plain_body_names_no_dictionary():
    assert codec.dictionary_id(codec.compress(FEED, level=LEVEL)) == codec.NO_DICTIONARY
    assert codec.dictionary_id(FEED) == codec.NO_DICTIONARY


def test_a_body_names_the_dictionary_that_compressed_it():
    """What makes a stored body self-describing, so reading never guesses."""
    trained = zstd.train_dict([FEED, PAGE] * 12, 110 * 1024)
    stored = codec.compress(FEED, level=LEVEL, dictionary=trained)

    assert codec.dictionary_id(stored) == trained.dict_id
    assert codec.decompress(stored, trained) == FEED


def test_a_dictionary_body_will_not_read_without_it():
    """The failure is loud. A silently wrong body would be far worse."""
    trained = zstd.train_dict([FEED, PAGE] * 12, 110 * 1024)
    stored = codec.compress(FEED, level=LEVEL, dictionary=trained)

    with pytest.raises(zstd.ZstdError):
        codec.decompress(stored)
