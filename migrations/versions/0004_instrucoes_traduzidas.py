"""instrucoes traduzidas

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-23 16:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('exercises') as batch_op:
        batch_op.add_column(sa.Column('instructions_pt', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('exercises') as batch_op:
        batch_op.drop_column('instructions_pt')
