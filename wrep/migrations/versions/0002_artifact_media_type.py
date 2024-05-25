"""artifact_media_type

Revision ID: 0002
Revises: 0001
Create Date: 2024-05-25 22:37:17.815898

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = '0001'


def upgrade() -> None:
    op.alter_column('artifact', 'mimetype', new_column_name='media_type')


def downgrade() -> None:
    op.alter_column('artifact', 'media_type', new_column_name='mimetype')
