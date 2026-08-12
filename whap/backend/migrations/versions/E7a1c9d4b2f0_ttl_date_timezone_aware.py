"""Make container_instance.ttl_date timezone-aware

Converts ttl_date from TIMESTAMP WITHOUT TIME ZONE to TIMESTAMP WITH TIME ZONE.
The application has always written UTC into this column, so existing naive values
are reinterpreted as UTC during the conversion (Postgres ``USING ... AT TIME ZONE
'UTC'``). This aligns ttl_date with the timezone-aware convention already used by
the other datetime columns in the model and removes the naive/aware mismatch in
prolong_container.

Revision ID: e7a1c9d4b2f0
Revises: 4255bc6846ba
Create Date: 2026-07-17 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e7a1c9d4b2f0'
down_revision = '4255bc6846ba'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        # Reinterpret stored naive timestamps as UTC while changing the type.
        op.alter_column(
            'container_instance',
            'ttl_date',
            existing_type=sa.DateTime(),
            type_=sa.DateTime(timezone=True),
            existing_nullable=True,
            postgresql_using="ttl_date AT TIME ZONE 'UTC'",
        )
    else:
        # SQLite (and others without a native tz type): a plain type change.
        # SQLite stores datetimes as text and ignores the tz flag, so this is a
        # metadata-only no-op that keeps autogenerate/round-tripping consistent.
        with op.batch_alter_table('container_instance', schema=None) as batch_op:
            batch_op.alter_column(
                'ttl_date',
                existing_type=sa.DateTime(),
                type_=sa.DateTime(timezone=True),
                existing_nullable=True,
            )


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.alter_column(
            'container_instance',
            'ttl_date',
            existing_type=sa.DateTime(timezone=True),
            type_=sa.DateTime(),
            existing_nullable=True,
            postgresql_using="ttl_date AT TIME ZONE 'UTC'",
        )
    else:
        with op.batch_alter_table('container_instance', schema=None) as batch_op:
            batch_op.alter_column(
                'ttl_date',
                existing_type=sa.DateTime(timezone=True),
                type_=sa.DateTime(),
                existing_nullable=True,
            )
