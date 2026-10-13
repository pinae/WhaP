"""The queue between a scheduled notification and the messages it becomes.

run_once() does two things, each safe to repeat after a crash:

1. A notification that is due becomes one delivery row per person and
   channel, with the message rendered for them. So does a due reminder.
2. Pending deliveries are sent: email over one SMTP connection per batch,
   Matrix one by one. A failure is retried after RETRY_AFTER; after
   MAX_ATTEMPTS tries, or at once if retrying can't help, it is failed.

One process at a time runs this: the worker starts run_notifications.py and
waits for it to finish before starting another.
"""
import logging
import secrets
from datetime import datetime, timedelta, UTC

from flask import current_app

from .. import db
from ..config import email_configured, matrix_configured
from ..models import Notification, NotificationDelivery, NotificationSettings
from ..services.ldap_service import LdapUnavailable
from . import audience, expiry, render
from .email_channel import EmailChannel
from .errors import DeliveryError
from .matrix_channel import MatrixChannel

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
RETRY_AFTER = (timedelta(minutes=1), timedelta(minutes=10))  # after the 1st and 2nd failure
BATCH = 100


def _now():
    return datetime.now(UTC)


def _due_notifications(now):
    return db.session.scalars(
        db.select(Notification)
        .where(Notification.status.in_(('scheduled', 'sending')))
        .where((Notification.send_at.is_(None)) | (Notification.send_at <= now))
        .order_by(Notification.id)).all()


def _due_reminders(now):
    return db.session.scalars(
        db.select(Notification)
        .where(Notification.status == 'sent', Notification.reminded_at.is_(None),
               Notification.remind_at.is_not(None), Notification.remind_at <= now)
        .order_by(Notification.id)).all()


def _due_deliveries(now, limit=BATCH):
    return db.session.scalars(
        db.select(NotificationDelivery)
        .where(NotificationDelivery.status == 'pending')
        .where((NotificationDelivery.next_attempt_at.is_(None)) | (NotificationDelivery.next_attempt_at <= now))
        .order_by(NotificationDelivery.id).limit(limit)).all()


def work_due(now=None):
    """Whether run_once() has anything to do. Cheap: the worker asks often."""
    now = now or _now()
    return bool(_due_notifications(now) or _due_reminders(now) or _due_deliveries(now, limit=1)
                or expiry.due(now))


def queue(notification, phase='notice', now=None):
    """Add the deliveries ``notification`` needs for ``phase``; returns how many were added.

    Deliveries that already exist are kept, so a dispatch interrupted half-way
    can simply run again.
    """
    config = current_app.config
    existing = set(db.session.execute(
        db.select(NotificationDelivery.user_uid, NotificationDelivery.channel)
        .where(NotificationDelivery.notification_id == notification.id, NotificationDelivery.phase == phase)).all())
    added = 0
    for recipient in audience.recipients(notification):
        channels = [c for c in recipient.channels() if (recipient.user_uid, c[0]) not in existing]
        if not channels:
            continue
        subject, body = render.render(notification, recipient, config, phase, now)
        for channel, address in channels:
            db.session.add(NotificationDelivery(
                notification_id=notification.id, user_uid=recipient.user_uid, channel=channel, phase=phase,
                address=address, subject=subject, body=body))
            added += 1
    return added


def dispatch(now=None):
    """Turn due notifications and reminders into deliveries."""
    now = now or _now()
    for notification in _due_notifications(now):
        notification.status = 'sending'
        db.session.commit()
        try:
            added = queue(notification, 'notice', now)
        except LdapUnavailable as e:
            db.session.rollback()
            log.warning(f"Notification {notification.id} waits: {e}")
            raise
        notification.status = 'sent'
        notification.sent_at = now
        db.session.commit()
        log.info(f"Notification {notification.id} queued {added} deliveries.")

    for notification in _due_reminders(now):
        try:
            added = queue(notification, 'reminder', now)
        except LdapUnavailable as e:
            db.session.rollback()
            log.warning(f"Reminder for notification {notification.id} waits: {e}")
            raise
        notification.reminded_at = now
        db.session.commit()
        log.info(f"Reminder for notification {notification.id} queued {added} deliveries.")


def _succeeded(delivery, now):
    delivery.status = 'sent'
    delivery.sent_at = now
    delivery.attempts += 1
    delivery.last_error = None
    delivery.next_attempt_at = None
    db.session.commit()


def _failed(delivery, error, now):
    delivery.attempts += 1
    delivery.last_error = str(error)
    if error.permanent or delivery.attempts >= MAX_ATTEMPTS:
        delivery.status = 'failed'
        delivery.next_attempt_at = None
    else:
        delivery.next_attempt_at = now + RETRY_AFTER[delivery.attempts - 1]
    db.session.commit()
    log.warning(f"Delivery {delivery.id} ({delivery.channel}) failed, attempt {delivery.attempts}: {error}")


def _message(delivery):
    return render.finish(delivery.notification, delivery.subject, delivery.body, current_app.config)


def _send_email(deliveries, now):
    if not deliveries:
        return
    attempted = set()
    try:
        with EmailChannel(current_app.config) as channel:
            for delivery in deliveries:
                attempted.add(delivery.id)
                message = _message(delivery)
                try:
                    channel.send(delivery.address, f"[WhaP] {message.subject}", message.text, message.html)
                except DeliveryError as e:
                    _failed(delivery, e, now)
                else:
                    _succeeded(delivery, now)
    except DeliveryError as e:  # no connection: none of the rest went out
        for delivery in deliveries:
            if delivery.id not in attempted:
                _failed(delivery, e, now)


def _send_matrix(deliveries, now):
    if not deliveries:
        return
    channel = MatrixChannel(current_app.config)
    for delivery in deliveries:
        settings = NotificationSettings.for_user(delivery.user_uid)
        if not (settings.matrix_enabled and settings.matrix_room_id and settings.matrix_id == delivery.address):
            _failed(delivery, DeliveryError("The user disconnected this Matrix account.", permanent=True), now)
            continue
        message = _message(delivery)
        try:
            channel.send(settings.matrix_room_id, f"{message.subject}\n\n{message.text}",
                         f"<p><strong>{render.html.escape(message.subject)}</strong></p>\n{message.html}",
                         txn_id=f"whap-delivery-{delivery.id}")
        except DeliveryError as e:
            _failed(delivery, e, now)
        else:
            _succeeded(delivery, now)


def send_directly(email, settings, message):
    """Send ``message`` now, not through the queue, on each channel that reaches a user.

    For test messages. Returns [{channel, address, ok, error?}], empty if no
    channel reaches them.
    """
    config = current_app.config
    results = []
    if settings.email_enabled and email and email_configured(config):
        try:
            with EmailChannel(config) as channel:
                channel.send(email, f"[WhaP] {message.subject}", message.text, message.html)
            results.append({'channel': 'email', 'address': email, 'ok': True})
        except DeliveryError as e:
            results.append({'channel': 'email', 'address': email, 'ok': False, 'error': str(e)})
    if 'matrix' in settings.channels() and matrix_configured(config):
        try:
            MatrixChannel(config).send(
                settings.matrix_room_id, f"{message.subject}\n\n{message.text}",
                f"<p><strong>{render.html.escape(message.subject)}</strong></p>\n{message.html}",
                txn_id=f"whap-direct-{secrets.token_hex(8)}")
            results.append({'channel': 'matrix', 'address': settings.matrix_id, 'ok': True})
        except DeliveryError as e:
            results.append({'channel': 'matrix', 'address': settings.matrix_id, 'ok': False, 'error': str(e)})
    return results


def deliver(now=None):
    """Send up to BATCH pending deliveries that are due."""
    now = now or _now()
    pending = _due_deliveries(now)
    _send_email([d for d in pending if d.channel == 'email'], now)
    _send_matrix([d for d in pending if d.channel == 'matrix'], now)
    return len(pending)


def run_once(now=None):
    """Create due expiry reminders, dispatch what is due, then send.

    LdapUnavailable stops dispatching but not sending.
    """
    now = now or _now()
    try:
        expiry.scan(now)
        dispatch(now)
    finally:
        deliver(now)
