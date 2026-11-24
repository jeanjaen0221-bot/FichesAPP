"""allergènes ajoutés dans Paramètres

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-24 19:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0007'
down_revision: Union[str, None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('allergene',
    sa.Column('cle', sa.String(length=50), nullable=False),
    sa.Column('libelle', sa.String(length=100), nullable=False),
    sa.Column('icone', sa.LargeBinary(), nullable=True),
    sa.Column('cree_le', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('cle')
    )


def downgrade() -> None:
    op.drop_table('allergene')
