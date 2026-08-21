"""image renditions

Images are 60% of this database — 397 MB against 128 MB of feed documents and 126 MB of
page captures — and almost none of that is information. 166 of 1720 captures are 45% of
the bytes: photographs served as 5000px PNG, 1 MB each on average against 139 KB for the
JPEGs. Two publishers alone account for a quarter of the whole database in 67 files.

Compression is not the answer and was measured not to be: zstd on 30 photographs moved
4.59 MB to 4.59 MB and the dictionary trainer refused every size, which is why
`image_captures` sits outside the codec path the other three body columns use. What works
is re-encoding. On the real bytes, an 11 MB PNG hero becomes 124 KB of AVIF at 1200px, and
JPEGs already at reading width still drop 46-54%.

So a rendition is to an image capture what an extraction is to a page capture: derived,
disposable, keyed on the recipe and what carried it out, rebuildable from bytes that are
never touched. `spec` is what was asked for and `encoder_version` is what answered, the
same bargain `extractor_version` and `parser_version` strike — bump either and the archive
is due again.

An empty `body` is an answer, not a failure: it means nothing beat the bytes as served, so
read the capture instead. Recording it is what stops the sweep offering that image every
five minutes forever, the same reason a feed carving is written even when the document
carried no text.

This makes the database *bigger*. The original is the archive and stays, so renditions are
additive until originals move behind the `s3` extra that has been sitting unused in
`pyproject.toml` since the start. What they buy today is a reader that fetches 124 KB
instead of 11 MB, which is the whole of the argument on a phone.

Also repaired here: one 404 error page, 52 KB of HTML, was linked as an article's lead
image. `accept` refuses a body by its declared type in the fetcher but only below 300, so
an error page arrives untyped and the slot took it. The guard is in `extract/images.py`;
this unlinks the row it already made, and the image sweep will offer that slot again.

Revision ID: 32c9fa7384fd
Revises: c4f1b6de20a7
Create Date: 2026-08-21 00:58:22.248162+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "32c9fa7384fd"
down_revision: str | Sequence[str] | None = "c4f1b6de20a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "image_renditions",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("image_capture_id", sa.UUID(), nullable=False),
        sa.Column("spec", sa.String(length=16), nullable=False),
        sa.Column("encoder_version", sa.String(length=32), nullable=False),
        sa.Column("content_type", sa.String(length=64), server_default="", nullable=False),
        sa.Column("width", sa.Integer(), server_default="0", nullable=False),
        sa.Column("height", sa.Integer(), server_default="0", nullable=False),
        sa.Column("body", sa.LargeBinary(), server_default=sa.text("''::bytea"), nullable=False),
        sa.Column("byte_size", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["image_capture_id"],
            ["image_captures.id"],
            name=op.f("fk_image_renditions_image_capture_id_image_captures"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_image_renditions")),
        sa.UniqueConstraint(
            "image_capture_id",
            "spec",
            "encoder_version",
            name="uq_image_renditions_capture_spec_encoder",
        ),
    )

    # The capture rows stay: they record what the publisher served, which is true whatever
    # it was. What has to go is the claim that one of them is an article's image.
    op.execute(
        """
        UPDATE extraction_images
           SET image_capture_id = NULL
         WHERE image_capture_id IN (
                   SELECT id FROM image_captures
                    WHERE status NOT BETWEEN 200 AND 299
                       OR content_type NOT LIKE 'image/%'
               )
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    # The unlinking is not reversed: the sweep re-satisfies those slots from a real answer,
    # and putting an error page back as a lead image is not a state worth restoring.
    op.drop_table("image_renditions")
