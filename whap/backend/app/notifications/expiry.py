"""Reminders before a local container's project directory is deleted.

The ttl daemon on each compute server deletes /home/<user>/<project> once
the date in its ttl.txt has passed. WhaP reminds the owner TTL_REMINDER_DAYS
before (default 7 and 1): one notification per container, ttl date and step,
so prolonging, which moves the date, starts the series again. Only the
nearest step that is due is sent: a container created three days before its
date gets the "7 days" reminder once, not a 7-day and a 1-day one at once.
"""
from datetime import datetime, timedelta, UTC

from flask import current_app

from .. import db
from ..config import reminder_days
from ..models import ContainerInstance, Notification

SUBJECT = "Your project “{project}” on {server} expires {expires_in}"
BODY = ("Hello {name},\n\n"
        "the local project directory {path} on {server} will be deleted on {ttl_date}. "
        "Everything in it that is not in ~/synced is lost then.\n\n"
        "Prolong it by 4 weeks: {prolong_url}\n\n"
        "If you no longer need it, there is nothing to do. Copy anything worth keeping to ~/synced "
        "first; it lives on the storage server and is not deleted.")


def _aware(value):
    # SQLite gives naive datetimes back; they are stored as UTC.
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


def steps():
    try:
        return reminder_days(current_app.config.get('TTL_REMINDER_DAYS') or '7,1')
    except ValueError:
        return [7, 1]


def is_local(image_name):
    return bool(image_name) and image_name.startswith('worker_local_')


def expiring(now, within):
    """Live local containers whose ttl date lies between now and now + within."""
    containers = db.session.scalars(
        db.select(ContainerInstance)
        .where(ContainerInstance.status != 'DELETED', ContainerInstance.ttl_date.is_not(None),
               ContainerInstance.image_name.like('worker\\_local\\_%', escape='\\'),
               ContainerInstance.ttl_date > now, ContainerInstance.ttl_date <= now + within)
        .order_by(ContainerInstance.ttl_date)).all()
    return [c for c in containers if is_local(c.image_name)]


def due_step(ttl_date, now, days):
    """The reminder step (days before) that applies now, or None if none is due yet."""
    applicable = [d for d in days if now >= _aware(ttl_date) - timedelta(days=d)]
    return min(applicable) if applicable else None


def dedupe_key(container, step):
    return f"expiry:{container.id}:{_aware(container.ttl_date).date().isoformat()}:{step}"


def _missing(now):
    days = steps()
    pending = []
    for container in expiring(now, timedelta(days=max(days))):
        step = due_step(container.ttl_date, now, days)
        if step is None:
            continue
        key = dedupe_key(container, step)
        if not db.session.scalar(db.select(Notification.id).where(Notification.dedupe_key == key)):
            pending.append((container, step, key))
    return pending


def due(now=None):
    """Whether a reminder should be created now. Cheap enough for the worker's checks."""
    return bool(_missing(now or datetime.now(UTC)))


def notification_for(container, step, key=None):
    """An (unsaved) expiry reminder for ``container``."""
    notification = Notification(
        kind='expiry', status='scheduled', subject=SUBJECT, body=BODY, dedupe_key=key,
        notice_until=_aware(container.ttl_date))
    notification.params_dict = {
        'container_id': container.id,
        'project': container.project.name if container.project else '',
        'server': container.compute_server.hostname if container.compute_server else '',
        'username': container.local_user.username if container.local_user else container.user_uid,
        'ttl_date': _aware(container.ttl_date).isoformat(),
        'days': step,
    }
    return notification


def scan(now=None):
    """Create the reminders that are due; returns how many. Each is sent like any notification."""
    now = now or datetime.now(UTC)
    created = 0
    for container, step, key in _missing(now):
        notification = notification_for(container, step, key)
        notification.send_at = now
        db.session.add(notification)
        created += 1
    db.session.commit()
    return created
