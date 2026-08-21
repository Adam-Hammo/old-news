"""images are re-encoded, not archived twice

Images are 57% of this database — 399 MB against 129 MB of feed documents and 128 MB of
page captures — and almost none of that is information. 166 of 1720 are 45% of the bytes:
photographs served as 5000px PNG, 1 MB each on average against 139 KB for the JPEGs. Two
publishers account for a quarter of the whole database in 67 files.

Compression is not the answer and was measured not to be: zstd over 30 photographs moved
4.59 MB to 4.59 MB and the dictionary trainer refused every size, which is why this table
sits outside the codec path the other three body columns use. Re-encoding is. On the real
bytes an 11 MB PNG hero becomes 124 KB of AVIF at reading width, and JPEGs already narrow
enough still drop 46-54%.

The first shape of this was an `image_renditions` table beside the capture, on the pattern
that serves extractions and carvings: keep the artefact, derive from it, throw the
derivation away freely. That pattern earns its place when the derivation is a judgement —
a better extractor really does read the same page better next year. Re-encoding is not
much of a judgement, and keeping both halves means storing the picture twice for the
privilege. So there is no second table: `spec` and `encoder_version` go on the capture and
the bytes are replaced in place.

That is the irreversible call, and it is worth writing down what it costs. What is held
after this is 1600px at quality 65. Anything wider is gone — a 5000px original cannot be
recovered, and the ceiling for any future rendering is now 1600px rather than whatever the
publisher sent. Measured across the corpus the alternatives were 1200px/q55 at 42 MB and
2000px/q75 at 88 MB; 1600px/q65 lands near 65 MB and was chosen because 14% of these
images are charts, logos and screenshots where low quality smears the type, and because it
still covers a 2x display.

What survives is the record of the fetch. `status`, `fetched_at`, `final_url`, `error` and
`body_hash` are untouched, and `body_hash` deliberately goes on describing the bytes as
served — it is half of `(url_digest, body_hash)`, which is what makes one image behind two
feeds one fetch, and it would stop doing that job if it followed the re-encoded body.

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
    # Empty means as served and not yet read, which is what every existing row is.
    for name, size in (("spec", 16), ("encoder_version", 32)):
        op.add_column(
            "image_captures",
            sa.Column(name, sa.String(length=size), server_default="", nullable=False),
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
    # Neither half is reversed. The unlinked slots are re-satisfied by the sweep from a
    # real answer, and no column ever held the bytes that were replaced.
    for name in ("encoder_version", "spec"):
        op.drop_column("image_captures", name)
