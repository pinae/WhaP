"""Project names: drop the global unique index left by the initial schema

f3b8d21a6c94 made project names unique per owner and dropped the global
uq_project_name, but the initial schema had also created ix_project_name as a
UNIQUE index. It survived, so on every migrated database two owners still could
not each have a project called "thesis". The models declare ix_project_name as
a plain index; this makes the database match.

Revision ID: 0736a97914ad
Revises: f3b8d21a6c94
Create Date: 2026-10-12 11:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '0736a97914ad'
down_revision = 'f3b8d21a6c94'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('project', schema=None) as batch_op:
        batch_op.drop_index('ix_project_name')
        batch_op.create_index('ix_project_name', ['name'], unique=False)


def downgrade():
    # Fails if two owners have a project of the same name; resolve those first.
    with op.batch_alter_table('project', schema=None) as batch_op:
        batch_op.drop_index('ix_project_name')
        batch_op.create_index('ix_project_name', ['name'], unique=True)
