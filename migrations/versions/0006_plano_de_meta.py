"""plano de meta de peso

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-23 19:30:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'goal_plans',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('profile_id', sa.Integer(), sa.ForeignKey('profiles.id', ondelete='CASCADE'), nullable=False),
        sa.Column('start_weight_kg', sa.Float(), nullable=False),
        sa.Column('target_weight_kg', sa.Float(), nullable=False),
        sa.Column('tdee_kcal', sa.Float(), nullable=False),
        sa.Column('scenarios', sa.JSON(), nullable=False),
        sa.Column('chosen', sa.String(length=20), nullable=False),
        sa.Column('analysis', sa.Text(), nullable=True),
        sa.Column('origin', sa.String(length=20), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_goal_plans_profile', 'goal_plans', ['profile_id', 'is_active'])


def downgrade() -> None:
    op.drop_index('ix_goal_plans_profile', 'goal_plans')
    op.drop_table('goal_plans')
