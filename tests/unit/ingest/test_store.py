"""Document bodies are stored compressed, and the ones stored before that still read."""

from compression import zstd

from old_news.ingest.store import decompress

FEED = b'<?xml version="1.0"?><rss><channel><title>x</title></channel></rss>' * 200


def test_a_compressed_body_reads_back_unchanged():
    assert decompress(zstd.compress(FEED)) == FEED


def test_an_uncompressed_body_is_returned_as_is():
    """No migration ran, so rows written before compression must still be readable."""
    assert decompress(FEED) == FEED


def test_compression_is_worth_doing_on_feed_xml():
    assert len(zstd.compress(FEED)) < len(FEED) / 4
