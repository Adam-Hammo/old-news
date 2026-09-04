"""file every feed under a tier and a window

Data, not schema, and a one-off. This is the filing for the forty-one feeds that exist
today, matched on title against what is deployed. A fresh install has no feeds when this
runs and gets nothing: subscriptions arrive at `wire` with no window and are promoted by
hand. That is the honest limit of seeding taste, and why the column default does the real
work.

Only rows still at the defaults are touched, so a window retuned later is never walked
back over. The windows come from measured publishing rates — roughly `N / items per week`,
so each feed holds a comparable number of rows — bent by what the tier is for. The wire
runs in hours because the Guardian alone is 120 items a day; the essays run in weeks
because at one a week a shorter window shows nothing at all.

Reverting resets every subscription to the column defaults. A data migration cannot tell
a seeded value from one set afterwards, and the revision below this one drops the columns
regardless.

Revision ID: 251a8cbf84f6
Revises: b7102d4a694e

"""

from collections.abc import Sequence

from alembic import op

revision: str = "251a8cbf84f6"
down_revision: str | Sequence[str] | None = "b7102d4a694e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FILING = """
    update subscriptions s
       set tier = v.tier, expires_after = v.keep_for
      from (values
           ('The Guardian', 'wire', interval '6 hours'),
           ('The Conversation', 'wire', interval '1 day'),
           ('ABC News', 'wire', interval '1 day'),
           ('SBS World News', 'wire', interval '1 day'),
           ('Kagi News - World', 'wire', interval '3 days'),
           ('Nautilus', 'archive', interval '3 days'),
           ('404 Media', 'archive', interval '3 days'),
           ('Rest of World -', 'archive', interval '7 days'),
           ('Pluralistic (Cory Doctorow)', 'archive', interval '14 days'),
           ('xkcd.com', 'archive', interval '14 days'),
           ('Crooked Timber', 'archive', interval '14 days'),
           ('Cam Wilson', 'archive', interval '42 days'),
           ('Strong Towns', 'archive', interval '42 days'),
           ('John Quiggin', 'archive', interval '42 days'),
           ('Michael West', 'archive', interval '42 days'),
           ('The NewsBlur Blog', 'archive', interval '42 days'),
           ('Human Transit', 'archive', interval '180 days'),
           ('ProPublica', 'kindle', interval '7 days'),
           ('Croakey Health Media', 'kindle', interval '7 days'),
           ('Quanta Magazine', 'kindle', interval '7 days'),
           ('Astral Codex Ten', 'kindle', interval '14 days'),
           ('Overland', 'kindle', interval '14 days'),
           ('Works in Progress', 'kindle', interval '14 days'),
           ('seangoedecke.com RSS feed', 'kindle', interval '14 days'),
           ('NOEMA', 'kindle', interval '42 days'),
           ('Ed Zitron''s Where''s Your Ed At', 'kindle', interval '42 days'),
           ('Construction Physics', 'kindle', interval '42 days'),
           ('Asterisk', 'kindle', interval '42 days'),
           ('bellingcat', 'kindle', interval '42 days'),
           ('By the Numbers', 'kindle', interval '42 days'),
           ('Citation Needed (Molly White)', 'kindle', interval '42 days'),
           ('The Climate Brink', 'kindle', interval '42 days'),
           ('The Markup', 'kindle', interval '42 days'),
           ('Worse on Purpose', 'kindle', interval '42 days'),
           ('Experimental History', 'kindle', interval '180 days'),
           ('Admiral Cloudberg', 'kindle', interval '180 days'),
           ('Lauren’s data Substack', 'kindle', interval '180 days'),
           ('Baldur Bjarnason''s Notes on the Web', 'kindle', interval '180 days'),
           ('Ludicity', 'kindle', interval '180 days'),
           ('Climate Town', 'kindle', interval '180 days'),
           ('Tedium: The Dull Side of the Internet.', 'kindle', interval '180 days')
           ) as v(title, tier, keep_for)
      join feeds f on f.title = v.title
     where s.feed_id = f.id
       and s.tier = 'wire'
       and s.expires_after is null
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(FILING)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("update subscriptions set tier = 'wire', expires_after = null")
