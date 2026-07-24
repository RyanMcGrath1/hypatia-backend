"""add totp_methods and mfa_login_challenges tables

Revision ID: a1b2c3d4e5f6
Revises: 4f79d292f18a
Create Date: 2026-07-23 22:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '4f79d292f18a'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'totp_methods',
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('secret_encrypted', sa.Text(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_timecode', sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'),
    )

    op.create_table(
        'mfa_login_challenges',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('attempt_count', sa.Integer(), nullable=False),
        sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('mfa_login_challenges', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_mfa_login_challenges_expires_at'),
            ['expires_at'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_mfa_login_challenges_token_hash'),
            ['token_hash'],
            unique=True,
        )
        batch_op.create_index(
            batch_op.f('ix_mfa_login_challenges_user_id'),
            ['user_id'],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table('mfa_login_challenges', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_mfa_login_challenges_user_id'))
        batch_op.drop_index(batch_op.f('ix_mfa_login_challenges_token_hash'))
        batch_op.drop_index(batch_op.f('ix_mfa_login_challenges_expires_at'))

    op.drop_table('mfa_login_challenges')
    op.drop_table('totp_methods')
