"""add "document" to records.record_type and records.original_filename

Lets an uploaded file be a document (txt/md/docx/hwp) that gets its text
extracted directly, not just an image parsed via OCR. original_filename lets
the UI tell several uploaded files apart (storage_path is UUID-based).

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-09-06 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, Sequence[str], None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_RECORD_TYPES = ("blog_url", "image", "text")
NEW_RECORD_TYPES = OLD_RECORD_TYPES + ("document",)


def upgrade() -> None:
    op.drop_constraint('ck_records_type', 'records', type_='check')
    op.create_check_constraint('ck_records_type', 'records', f"record_type IN {NEW_RECORD_TYPES}")
    op.add_column('records', sa.Column('original_filename', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('records', 'original_filename')
    op.drop_constraint('ck_records_type', 'records', type_='check')
    op.create_check_constraint('ck_records_type', 'records', f"record_type IN {OLD_RECORD_TYPES}")
