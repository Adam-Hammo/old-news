"""unlink error pages from image slots, again

The previous revision unlinked a 404 error page that was serving as an article's lead
image. The image sweep re-linked it within minutes, because the fix it shipped alongside
was incomplete: `_store` stopped pointing a slot at a body that had not answered, and
`link_existing` — the path that reuses a capture already held for a URL — had never
checked at all. Unlinking made the slot due, the sweep offered it, and the reuse path
handed the same error page straight back.

Both now ask `ImageCapture.usable`, one hybrid, so there is nowhere left for the two to
disagree. This revision repeats the repair with that in place.

Kept as its own revision rather than folded into the last one: that migration has run on
the deployment, so editing it would mean the repair never runs again where it is needed.

Revision ID: 8b1e4a90c7d2
Revises: 32c9fa7384fd
Create Date: 2026-08-21 05:30:00.000000+00:00

"""

from collections.abc import Sequence

from alembic import op

revision: str = "8b1e4a90c7d2"
down_revision: str | Sequence[str] | None = "32c9fa7384fd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        UPDATE extraction_images
           SET image_capture_id = NULL
         WHERE image_capture_id IN (
                   SELECT id FROM image_captures
                    WHERE body = ''::bytea
                       OR status NOT BETWEEN 200 AND 299
                       OR content_type NOT LIKE 'image/%'
               )
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Nothing to undo: a slot pointing at an error page is not a state worth restoring,
    # and the sweep fills it from a real answer when there is one.
