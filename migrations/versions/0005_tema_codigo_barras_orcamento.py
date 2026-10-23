"""tema do perfil, codigo de barras e orcamento por mes

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-23 19:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('profiles') as batch_op:
        batch_op.add_column(sa.Column('theme', sa.String(length=20), nullable=True))
    with op.batch_alter_table('products') as batch_op:
        batch_op.add_column(sa.Column('barcode', sa.String(length=32), nullable=True))
        batch_op.create_index('ix_products_barcode', ['barcode'])
    op.create_table(
        'monthly_budgets',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('profile_id', sa.Integer(), sa.ForeignKey('profiles.id', ondelete='CASCADE'), nullable=False),
        sa.Column('month', sa.String(length=7), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2, asdecimal=True), nullable=False),
        sa.UniqueConstraint('profile_id', 'month', name='uq_budget_month'),
    )


def downgrade() -> None:
    op.drop_table('monthly_budgets')
    with op.batch_alter_table('products') as batch_op:
        batch_op.drop_index('ix_products_barcode')
        batch_op.drop_column('barcode')
    with op.batch_alter_table('profiles') as batch_op:
        batch_op.drop_column('theme')
