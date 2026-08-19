from old_news.robots import allow_everything, parse

GUARDIAN = """
User-agent: *
Crawl-delay: 10
Disallow: /print/
Disallow: /*/subscriber-only
Allow: /print/free

User-agent: old-news
Disallow: /nope
"""


def test_an_absent_robots_txt_allows_everything():
    rules = allow_everything("old-news")

    assert rules.allows("/anything")
    assert rules.crawl_delay is None


def test_parse_without_modified_would_disallow_everything():
    """The stdlib treats an unstamped parser as unanswerable, so `parse` stamps it.
    Without that this returns False and the fetcher stops fetching anything."""
    assert parse("User-agent: *\nAllow: /", user_agent="old-news").allows("/anything")


def test_our_own_record_is_the_one_that_applies():
    rules = parse(GUARDIAN, user_agent="old-news")

    assert not rules.allows("/nope")
    # Records do not merge: the `*` block's rules are not ours to obey.
    assert rules.allows("/print/anything")
    assert rules.crawl_delay is None


def test_the_star_record_applies_to_everyone_else():
    rules = parse(GUARDIAN, user_agent="SomeCrawler")

    assert not rules.allows("/print/anything")
    assert not rules.allows("https://www.theguardian.com/uk/subscriber-only")
    # Allow wins on the longer match.
    assert rules.allows("/print/free")
    assert rules.crawl_delay == 10.0


def test_a_query_string_is_part_of_the_match():
    rules = parse("User-agent: *\nDisallow: /*?print=1", user_agent="old-news")

    assert not rules.allows("/article?print=1")
    assert rules.allows("/article")


def test_an_absurd_crawl_delay_is_capped():
    """Honour the request, but an hour per request would park a batch for days."""
    rules = parse("User-agent: *\nCrawl-delay: 3600", user_agent="old-news", max_crawl_delay=120.0)

    assert rules.crawl_delay == 120.0


def test_a_disallow_all_is_obeyed():
    rules = parse("User-agent: *\nDisallow: /", user_agent="old-news")

    assert not rules.allows("/")
    assert not rules.allows("/anything")


def test_robots_txt_itself_is_always_allowed():
    """Otherwise a Disallow: / would stop us ever refreshing the rules."""
    assert parse("User-agent: *\nDisallow: /", user_agent="old-news").allows("/robots.txt")


def test_a_blanket_ban_is_recognisable():
    """The distinction feed polls turn on: a rule about everything, or about us."""
    assert parse("User-agent: *\nDisallow: /", user_agent="old-news").blocks_everything
    assert not parse("User-agent: *\nDisallow: /print/", user_agent="old-news").blocks_everything
    assert not allow_everything("old-news").blocks_everything


def test_a_blanket_ban_with_the_feed_allowed_is_not_a_ban_on_the_feed():
    rules = parse("User-agent: *\nDisallow: /\nAllow: /feed.xml", user_agent="old-news")

    assert rules.blocks_everything
    assert rules.allows("/feed.xml")


def test_a_wildcard_rule_matching_a_query_string_is_obeyed():
    """Medium disallows `/*/*source=`, and every article link in its own feed carries
    `?source=rss-…`. The stdlib parser percent-encodes the `=` in the rule and not the
    one in the query, so this rule silently never fired."""
    rules = parse("User-agent: *\nDisallow: /*/*source=\n", user_agent="old-news")

    assert not rules.allows("https://medium.com/the-academic/dark-networks-abc?source=rss-x")
    # One path segment, so the rule does not reach it. Not every Medium URL is blocked.
    assert rules.allows("https://admiralcloudberg.medium.com/trial-by-fire-abc?source=rss-x")


def test_an_anchored_wildcard_allow_is_a_known_protego_bug():
    """scrapy/protego#51, open since 2024 and still present in 0.6.2: an `Allow` that
    both contains a wildcard and ends in `$` is not applied. No host in this corpus
    writes one — this fails the day one does, rather than quietly denying a page."""
    rules = parse("User-agent: *\nAllow: /*/filter/page=*/$\nDisallow: /\n", user_agent="old-news")

    assert not rules.allows("https://example.com/1/filter/page=5/"), (
        "protego#51 appears to be fixed — this expectation should be inverted"
    )
