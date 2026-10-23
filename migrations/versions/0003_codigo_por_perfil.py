"""codigo de acesso por perfil

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-23 15:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('profiles') as batch_op:
        batch_op.add_column(sa.Column('access_hash', sa.String(length=200), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('profiles') as batch_op:
        batch_op.drop_column('access_hash')
