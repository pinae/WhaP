"""Add groups and migrate admin users

Revision ID: a36e2d3d3e2a
Revises: 7411f93b43ae
Create Date: 2025-07-16 15:11:16.595564

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a36e2d3d3e2a'
down_revision = '7411f93b43ae'
branch_labels = None
depends_on = None


def upgrade():
    # ### Part 1: Auto-generated schema creation ###
    group_table = op.create_table('group',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('image_whitelist', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('group_compute_server_access',
    sa.Column('group_id', sa.Integer(), nullable=False),
    sa.Column('compute_server_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['compute_server_id'], ['compute_server.id'], ),
    sa.ForeignKeyConstraint(['group_id'], ['group.id'], ),
    sa.PrimaryKeyConstraint('group_id', 'compute_server_id')
    )
    op.create_table('group_gpu_access',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('group_id', sa.Integer(), nullable=False),
    sa.Column('compute_server_id', sa.Integer(), nullable=False),
    sa.Column('allowed_gpus', sa.String(length=255), nullable=False),
    sa.ForeignKeyConstraint(['compute_server_id'], ['compute_server.id'], ),
    sa.ForeignKeyConstraint(['group_id'], ['group.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('group_id', 'compute_server_id', name='_group_server_gpu_uc')
    )
    group_membership_table = op.create_table('group_membership',
    sa.Column('user_uid', sa.String(length=128), nullable=False),
    sa.Column('group_id', sa.Integer(), nullable=False),
    sa.Column('is_group_admin', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['group_id'], ['group.id'], ),
    sa.PrimaryKeyConstraint('user_uid', 'group_id')
    )
    with op.batch_alter_table('project', schema=None) as batch_op:
        batch_op.add_column(sa.Column('owner_group_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_project_owner_group_id'), ['owner_group_id'], unique=False)
        # Temporarily named to avoid conflicts during downgrade/upgrade cycles
        batch_op.create_foreign_key('fk_project_owner_group_id', 'group', ['owner_group_id'], ['id'])
        # Drop old constraint and add new one
        batch_op.drop_constraint('cc_project_owner', type_='check')
        batch_op.create_check_constraint(
            'cc_project_owner_exclusive',
            '(owner_uid IS NOT NULL AND owner_local_user_id IS NULL AND owner_group_id IS NULL) OR '
            '(owner_uid IS NULL AND owner_local_user_id IS NOT NULL AND owner_group_id IS NULL) OR '
            '(owner_uid IS NULL AND owner_local_user_id IS NULL AND owner_group_id IS NOT NULL)'
        )

    # ### Part 2: Custom data migration ###
    # Create the Admins group with ID 0
    op.bulk_insert(group_table, [{'id': 0, 'name': 'Admins', 'image_whitelist': '*'}])
    # Reset the sequence for the 'id' column to prevent key collisions
    op.execute("SELECT setval(pg_get_serial_sequence('group', 'id'), coalesce(max(id), 0)+1, false) FROM \"group\";")

    # Bind to the current session to query for existing admins
    bind = op.get_bind()
    session = sa.orm.Session(bind=bind)

    # Define a lightweight representation of the local_user table to query it
    local_user_table = sa.Table('local_user', sa.MetaData(),
                                sa.Column('id', sa.Integer, primary_key=True),
                                sa.Column('is_admin', sa.Boolean))

    # Find all users that have the old is_admin flag set to True
    old_admins = session.query(local_user_table).filter(local_user_table.c.is_admin == True).all()

    admin_memberships = []
    for admin in old_admins:
        admin_memberships.append({
            'user_uid': f'local:{admin.id}',
            'group_id': 0,
            'is_group_admin': True
        })

    # If any admins were found, add them to the group_membership table
    if admin_memberships:
        op.bulk_insert(group_membership_table, admin_memberships)

    # Finally, drop the now-obsolete is_admin column from local_user
    with op.batch_alter_table('local_user', schema=None) as batch_op:
        batch_op.drop_column('is_admin')

    # ### end Alembic commands ###


def downgrade():
    # ### Part 1: Custom data migration reversal ###
    # Add the is_admin column back to the local_user table
    with op.batch_alter_table('local_user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_admin', sa.Boolean(), server_default='false', nullable=False))

    # This part is best-effort. If you need to downgrade, this will attempt
    # to set the is_admin flag for any users who were in the Admins group.
    op.execute(
        "UPDATE local_user SET is_admin = TRUE WHERE 'local:' || id IN (SELECT user_uid FROM group_membership WHERE group_id = 0)"
    )

    # ### Part 2: Auto-generated schema reversal ###
    with op.batch_alter_table('project', schema=None) as batch_op:
        batch_op.drop_constraint('cc_project_owner_exclusive', type_='check')
        batch_op.create_check_constraint('cc_project_owner', '(owner_uid IS NOT NULL AND owner_local_user_id IS NULL) OR (owner_uid IS NULL AND owner_local_user_id IS NOT NULL)')
        batch_op.drop_constraint('fk_project_owner_group_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_project_owner_group_id'))
        batch_op.drop_column('owner_group_id')

    op.drop_table('group_membership')
    op.drop_table('group_gpu_access')
    op.drop_table('group_compute_server_access')
    op.drop_table('group')
    # ### end Alembic commands ###
