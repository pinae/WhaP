"""Project name unique per owner, not globally

Replaces the global uq_project_name (name) with three partial unique indexes,
one per owner kind, each scoped to rows where that owner column is set:
  * uq_project_name_owner_local  (name, owner_local_user_id) WHERE owner_local_user_id IS NOT NULL
  * uq_project_name_owner_uid    (name, owner_uid)           WHERE owner_uid IS NOT NULL
  * uq_project_name_owner_group  (name, owner_group_id)      WHERE owner_group_id IS NOT NULL

A plain composite UNIQUE(name, owner_uid, owner_local_user_id, owner_group_id)
would NOT enforce this: two of the three owner columns are always NULL and SQL
treats NULLs as distinct, so same-owner duplicates would pass. Partial indexes
avoid the NULL columns entirely. Two different owners may then each have a
project called e.g. "thesis"; a single owner still cannot.

Revision ID: f3b8d21a6c94
Revises: e7a1c9d4b2f0
Create Date: 2026-07-17 00:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f3b8d21a6c94'
down_revision = 'e7a1c9d4b2f0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('project', schema=None) as batch_op:
        batch_op.drop_constraint('uq_project_name', type_='unique')
        batch_op.create_index(
            'uq_project_name_owner_local', ['name', 'owner_local_user_id'],
            unique=True, sqlite_where=sa.text('owner_local_user_id IS NOT NULL'),
            postgresql_where=sa.text('owner_local_user_id IS NOT NULL'))
        batch_op.create_index(
            'uq_project_name_owner_uid', ['name', 'owner_uid'],
            unique=True, sqlite_where=sa.text('owner_uid IS NOT NULL'),
            postgresql_where=sa.text('owner_uid IS NOT NULL'))
        batch_op.create_index(
            'uq_project_name_owner_group', ['name', 'owner_group_id'],
            unique=True, sqlite_where=sa.text('owner_group_id IS NOT NULL'),
            postgresql_where=sa.text('owner_group_id IS NOT NULL'))


def downgrade():
    # Note: reverting requires globally-unique names. If per-owner duplicates
    # exist, recreating the global constraint will fail until resolved by hand.
    with op.batch_alter_table('project', schema=None) as batch_op:
        batch_op.drop_index('uq_project_name_owner_group')
        batch_op.drop_index('uq_project_name_owner_uid')
        batch_op.drop_index('uq_project_name_owner_local')
        batch_op.create_unique_constraint('uq_project_name', ['name'])
