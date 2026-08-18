from old_news.politeness import gap_for, stagger


def test_each_host_is_staggered_independently():
    """Position within its own host, so a busy publisher never delays a quiet one."""
    hosts = ["guardian", "bbc", "guardian", "guardian", "bbc"]

    assert stagger(hosts, minimum=5.0) == [0.0, 0.0, 5.0, 10.0, 5.0]


def test_a_zero_gap_disables_the_stagger():
    assert stagger(["guardian"] * 3, minimum=0.0) == [0.0, 0.0, 0.0]


def test_stagger_returns_one_delay_per_job():
    assert len(stagger((h for h in "abcab"), minimum=1.0)) == 5


def test_crawl_delay_lengthens_the_gap_for_that_host_only():
    hosts = ["guardian", "guardian", "bbc", "bbc"]

    delays = stagger(hosts, minimum=5.0, crawl_delays={"guardian": 30.0})

    assert delays == [0.0, 30.0, 0.0, 5.0]


def test_a_crawl_delay_may_only_lengthen_the_wait():
    """A publisher asking for less than our own floor doesn't get to speed us up."""
    assert gap_for("bbc", minimum=5.0, crawl_delays={"bbc": 1.0}) == 5.0
    assert gap_for("bbc", minimum=5.0, crawl_delays={"bbc": 20.0}) == 20.0
    assert gap_for("unknown", minimum=5.0, crawl_delays={}) == 5.0
