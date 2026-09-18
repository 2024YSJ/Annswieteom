"""merge share_slug and category_taxonomy heads

Revision ID: f72fc7d821b2
Revises: 6fa82e770439, b7e2f4a9c1d5
Create Date: 2026-09-18 12:46:35.416331

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f72fc7d821b2'
down_revision: Union[str, Sequence[str], None] = ('6fa82e770439', 'b7e2f4a9c1d5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
