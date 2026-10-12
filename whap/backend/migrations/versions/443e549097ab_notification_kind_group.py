"""Notifications to the members of WhaP groups: allow kind 'group'

Revision ID: 443e549097ab
Revises: 1468e85c78c4
Create Date: 2026-10-13 09:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '443e549097ab'
down_revision = '1468e85c78c4'
branch_labels = None
depends_on = None

KINDS = "'maintenance', 'image', 'dataset', 'expiry', 'announcement'"


def _kinds(kinds):
    with op.batch_alter_table('notification', schema=None) as batch_op:
        batch_op.drop_constraint('cc_notification_kind', type_='check')
        batch_op.create_check_constraint('cc_notification_kind', f"kind IN ({kinds})")


def upgrade():
    _kinds(KINDS + ", 'group'")


def downgrade():
    # Fails while group notifications exist; delete them first.
    _kinds(KINDS)
