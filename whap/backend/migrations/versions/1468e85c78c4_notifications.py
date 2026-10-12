"""Notifications: settings, messages, deliveries; container mounts; local user email

Adds what the notification feature stores:
  * notification_settings  per user: channels, topics, Matrix verification
  * notification           a message an admin (or the expiry scan) sends
  * notification_delivery  one message to one user over one channel
  * container_mount        what each container bind-mounts, so WhaP can tell
                           who uses a dataset
  * local_user.email       where local users' notifications go

Mounts were stored only in each container's create job (extravars JSON);
upgrade() copies them into container_mount for existing containers.

Revision ID: 1468e85c78c4
Revises: 0736a97914ad
Create Date: 2026-10-12 12:00:00.000000

"""
import json
import os

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '1468e85c78c4'
down_revision = '0736a97914ad'
branch_labels = None
depends_on = None


def _datasets_base():
    try:
        from flask import current_app
        return current_app.config.get('DATASETS_BASE_PATH')
    except RuntimeError:  # no app context, e.g. plain `alembic upgrade`
        return os.environ.get('DATASETS_BASE_PATH', '/data/DATASETS')


def _dataset_name(host_path, datasets_base):
    # Same rule as app.services.volume_service.dataset_name, copied so the
    # migration does not change when the application does.
    if not host_path or not datasets_base:
        return None
    parent, name = os.path.split(os.path.normpath(host_path))
    return name if parent == os.path.normpath(datasets_base) and name else None


def backfill_mounts(bind, datasets_base):
    """Copy each container's mounts from its first create job into container_mount."""
    jobs = bind.execute(sa.text(
        "SELECT container_instance_id, extravars FROM ansible_job "
        "WHERE action = 'create' AND extravars IS NOT NULL ORDER BY id"
    )).fetchall()
    done = set()
    rows = []
    for container_id, extravars in jobs:
        if container_id in done:
            continue
        done.add(container_id)
        try:
            volumes = json.loads(extravars).get('additional_volumes') or []
        except (ValueError, AttributeError):
            continue
        for vol in volumes:
            if not isinstance(vol, dict) or not vol.get('host_path') or not vol.get('container_path'):
                continue
            rows.append({
                'container_id': container_id,
                'host_path': vol['host_path'],
                'container_path': vol['container_path'],
                'writable': bool(vol.get('is_writable')),
                'dataset': _dataset_name(vol['host_path'], datasets_base),
            })
    if rows:
        bind.execute(sa.text(
            "INSERT INTO container_mount (container_id, host_path, container_path, writable, dataset) "
            "VALUES (:container_id, :host_path, :container_path, :writable, :dataset)"
        ), rows)


def upgrade():
    with op.batch_alter_table('local_user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email', sa.String(length=255), nullable=True))

    op.create_table(
        'container_mount',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('container_id', sa.Integer(), nullable=False),
        sa.Column('host_path', sa.String(length=1024), nullable=False),
        sa.Column('container_path', sa.String(length=1024), nullable=False),
        sa.Column('writable', sa.Boolean(), nullable=False),
        sa.Column('dataset', sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(['container_id'], ['container_instance.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('container_mount', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_container_mount_container_id'), ['container_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_container_mount_dataset'), ['dataset'], unique=False)

    op.create_table(
        'notification_settings',
        sa.Column('user_uid', sa.String(length=128), nullable=False),
        sa.Column('email_enabled', sa.Boolean(), nullable=False),
        sa.Column('matrix_enabled', sa.Boolean(), nullable=False),
        sa.Column('matrix_id', sa.String(length=255), nullable=True),
        sa.Column('matrix_room_id', sa.String(length=255), nullable=True),
        sa.Column('matrix_pending_id', sa.String(length=255), nullable=True),
        sa.Column('matrix_pending_room_id', sa.String(length=255), nullable=True),
        sa.Column('matrix_code_hash', sa.String(length=256), nullable=True),
        sa.Column('matrix_code_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('matrix_code_attempts', sa.Integer(), nullable=False),
        sa.Column('topic_maintenance', sa.Boolean(), nullable=False),
        sa.Column('topic_expiry', sa.Boolean(), nullable=False),
        sa.Column('topic_image', sa.Boolean(), nullable=False),
        sa.Column('topic_dataset', sa.Boolean(), nullable=False),
        sa.Column('all_off_acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('user_uid'),
    )

    op.create_table(
        'notification',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('subject', sa.String(length=255), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('params', sa.Text(), nullable=False),
        sa.Column('send_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('remind_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('notice_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('dedupe_key', sa.String(length=255), nullable=True),
        sa.Column('created_by', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reminded_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('maintenance', 'image', 'dataset', 'expiry', 'announcement')",
                           name='cc_notification_kind'),
        sa.CheckConstraint("status IN ('draft', 'scheduled', 'sending', 'sent', 'cancelled')",
                           name='cc_notification_status'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('dedupe_key'),
    )
    with op.batch_alter_table('notification', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_notification_kind'), ['kind'], unique=False)
        batch_op.create_index(batch_op.f('ix_notification_status'), ['status'], unique=False)

    op.create_table(
        'notification_delivery',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('notification_id', sa.Integer(), nullable=False),
        sa.Column('user_uid', sa.String(length=128), nullable=False),
        sa.Column('channel', sa.String(length=16), nullable=False),
        sa.Column('phase', sa.String(length=16), nullable=False),
        sa.Column('address', sa.String(length=255), nullable=True),
        sa.Column('subject', sa.String(length=255), nullable=True),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("channel IN ('email', 'matrix')", name='cc_delivery_channel'),
        sa.CheckConstraint("phase IN ('notice', 'reminder')", name='cc_delivery_phase'),
        sa.CheckConstraint("status IN ('pending', 'sent', 'failed')", name='cc_delivery_status'),
        sa.ForeignKeyConstraint(['notification_id'], ['notification.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('notification_id', 'user_uid', 'channel', 'phase', name='uq_delivery_once'),
    )
    with op.batch_alter_table('notification_delivery', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_notification_delivery_notification_id'), ['notification_id'],
                              unique=False)
        batch_op.create_index(batch_op.f('ix_notification_delivery_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_notification_delivery_user_uid'), ['user_uid'], unique=False)

    backfill_mounts(op.get_bind(), _datasets_base())


def downgrade():
    op.drop_table('notification_delivery')
    op.drop_table('notification')
    op.drop_table('notification_settings')
    op.drop_table('container_mount')
    with op.batch_alter_table('local_user', schema=None) as batch_op:
        batch_op.drop_column('email')
