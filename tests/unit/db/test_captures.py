"""What a capture row means, on instances that never reach Postgres."""

from old_news.db import CAPTURE_POLICY, CaptureOutcome, PageCapture


def test_succeeded_follows_the_outcome_not_the_status():
    """They agree for every row written today, because `_outcome_for` reads `response.ok`.
    That agreement is not the definition: `outcome` is what was decided, and the partial
    index behind `succeeded` is built on the same predicate. A row with a 2xx status and a
    declined outcome must not read as a page worth extracting."""
    declined = PageCapture(status=200, outcome=CaptureOutcome.DISALLOWED)
    answered = PageCapture(status=0, outcome=CaptureOutcome.OK)

    assert not declined.succeeded
    assert answered.succeeded


def test_a_capture_states_the_policy_it_was_asked_under():
    """The default is the old policy, so a row written without saying is not counted as
    having been asked the way we ask now."""
    assert PageCapture.capture_policy.default is None
    assert PageCapture(capture_policy=CAPTURE_POLICY).capture_policy == CAPTURE_POLICY
