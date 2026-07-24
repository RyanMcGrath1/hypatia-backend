"""add account_events.request_id and user_agent

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-24 03:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('account_events', schema=None) as batch_op:
        batch_op.add_column(sa.Column('request_id', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('user_agent', sa.String(length=512), nullable=True))
        batch_op.create_index(
            batch_op.f('ix_account_events_request_id'),
            ['request_id'],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table('account_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_account_events_request_id'))
        batch_op.drop_column('user_agent')
        batch_op.drop_column('request_id')
