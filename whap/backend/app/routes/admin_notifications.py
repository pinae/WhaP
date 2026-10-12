"""Admins compose notifications: choose who, write, preview, test, schedule, follow up.

A notification is a draft until scheduled; while scheduled it can still be
edited or cancelled. The worker turns it into deliveries at its time (see
app.notifications.dispatch), after which it is read-only: its deliveries can
be inspected and failed ones retried, and a copy or follow-up started.
"""
import os
from collections import Counter
from datetime import datetime, UTC

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import func

from .. import admin_required, db
from ..config import email_configured, matrix_configured
from ..models import (
    ComputeServer, ContainerInstance, ContainerMount, Group, GroupMembership, LocalUser, Notification,
    NotificationDelivery, NotificationSettings,
)
from ..notifications import audience, compose, dispatch, render
from ..notifications.audience import Recipient
from ..notifications.compose import ComposeError
from ..services.ldap_service import LdapUnavailable
from ..services.notification_service import get_user_email
from .permissions import _get_all_system_images

notif_bp = Blueprint('admin_notifications', __name__)

EDITABLE = ('draft', 'scheduled')
LDAP_DOWN = ("LDAP can't be reached, so WhaP can't tell who would get this. Try again in a moment.")


def _now():
    return datetime.now(UTC)


def _zone():
    return current_app.config.get('TIMEZONE') or 'UTC'


def _json():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ComposeError("Send the notification as JSON.")
    return data


def _about(notification):
    """What it is about, for lists: servers, image, dataset, groups or everyone."""
    params = notification.params_dict
    if notification.kind == 'maintenance':
        return render.server_names(params)
    if notification.kind == 'group':
        return render.group_names(params)
    if notification.kind == 'announcement':
        return 'Everyone'
    if notification.kind == 'expiry':
        return params.get('project', '')
    return params.get(notification.kind, '')


def _summary(notification):
    rows = db.session.execute(
        db.select(NotificationDelivery.status, func.count())
        .where(NotificationDelivery.notification_id == notification.id)
        .group_by(NotificationDelivery.status)).all()
    users = db.session.scalar(
        db.select(func.count(func.distinct(NotificationDelivery.user_uid)))
        .where(NotificationDelivery.notification_id == notification.id))
    counts = {'pending': 0, 'sent': 0, 'failed': 0, **dict(rows)}
    # The subject with what is the same for everyone filled in, for lists.
    title = ' '.join(render.fill(notification.subject, render.common_fields(notification, current_app.config)).split())
    return {**notification.to_dict(), 'title': title, 'about': _about(notification), 'deliveries': counts,
            'recipients': users, 'editable': notification.status in EDITABLE}


def _transient(data):
    """An unsaved Notification from a composer request, for audience and preview."""
    kind = data.get('kind')
    params = compose.clean_params(kind, data.get('params'), _zone())
    notification = Notification(kind=kind, subject=data.get('subject') or '', body=data.get('body') or '')
    notification.params_dict = params
    return notification


def _recipient_dict(recipient):
    return {
        'user_uid': recipient.user_uid,
        'username': recipient.username,
        'name': recipient.name,
        'containers': [{'id': c.id, 'project': c.project.name if c.project else None, 'image': c.image_name,
                        'server': c.compute_server.hostname if c.compute_server else None, 'status': c.status}
                       for c in recipient.containers],
        'channels': [{'channel': channel, 'address': address} for channel, address in recipient.channels()],
        'unreachable': recipient.unreachable,
    }


def _audience_summary(recipients):
    channels = Counter(channel for r in recipients for channel, _ in r.channels())
    unreachable = Counter(r.unreachable for r in recipients if r.unreachable)
    return {'total': len(recipients), 'reached': sum(1 for r in recipients if not r.unreachable),
            'email': channels['email'], 'matrix': channels['matrix'],
            'unreachable': {reason: unreachable[reason] for reason in ('topic_off', 'all_off', 'no_address')}}


def _me_as_recipient(kind):
    """The admin, for previews of a notification nobody would get yet."""
    uid = current_user.get_id()
    return Recipient(user_uid=uid, username=current_user.username, name=current_user.username,
                     email=get_user_email(uid), settings=NotificationSettings.for_user(uid), kind=kind)


def _message(notification, recipient, phase='notice'):
    config = current_app.config
    subject, body = render.render(notification, recipient, config, phase)
    message = render.finish(notification, subject, body, config)
    return {
        'email': {'subject': f"[WhaP] {message.subject}", 'text': message.text, 'html': message.html,
                  'to': recipient.email},
        'matrix': {'text': f"{message.subject}\n\n{message.text}",
                   'html': f"<p><strong>{render.html.escape(message.subject)}</strong></p>\n{message.html}"},
    }


@notif_bp.errorhandler(ComposeError)
def _compose_error(e):
    return jsonify({'message': str(e)}), 400


@notif_bp.errorhandler(LdapUnavailable)
def _ldap_down(e):
    current_app.logger.warning(f"Notification composer: {e}")
    return jsonify({'message': LDAP_DOWN}), 503


# --- choices for the composer -----------------------------------------------------

@notif_bp.route('/admin/notifications/options', methods=['GET'])
@login_required
@admin_required
def options():
    live = ContainerInstance.status != 'DELETED'
    per_server = dict(db.session.execute(
        db.select(ContainerInstance.compute_server_id, func.count()).where(live)
        .group_by(ContainerInstance.compute_server_id)).all())
    per_image = dict(db.session.execute(
        db.select(ContainerInstance.image_name, func.count()).where(live)
        .group_by(ContainerInstance.image_name)).all())
    per_dataset = dict(db.session.execute(
        db.select(ContainerMount.dataset, func.count(func.distinct(ContainerMount.container_id)))
        .join(ContainerInstance).where(live, ContainerMount.dataset.is_not(None))
        .group_by(ContainerMount.dataset)).all())
    members = dict(db.session.execute(
        db.select(GroupMembership.group_id, func.count()).group_by(GroupMembership.group_id)).all())

    images = {image['id'] for image in (_get_all_system_images(current_app)[0] or [])} | set(per_image)
    datasets_dir = current_app.config.get('DATASETS_BASE_PATH')
    datasets = set(per_dataset)
    if datasets_dir and os.path.isdir(datasets_dir):
        datasets |= {d for d in os.listdir(datasets_dir) if os.path.isdir(os.path.join(datasets_dir, d))}

    config = current_app.config
    return jsonify({
        'servers': [{'id': s.id, 'hostname': s.hostname, 'containers': per_server.get(s.id, 0)}
                    for s in db.session.scalars(db.select(ComputeServer).order_by(ComputeServer.hostname))],
        'images': [{'name': name, 'containers': per_image.get(name, 0)} for name in sorted(images)],
        'datasets': [{'name': name, 'containers': per_dataset.get(name, 0)} for name in sorted(datasets)],
        'groups': [{'id': g.id, 'name': g.name, 'members': members.get(g.id, 0)}
                   for g in db.session.scalars(db.select(Group).order_by(Group.name))],
        'templates': compose.TEMPLATES,
        'fields': compose.FIELDS,
        'impacts': compose.IMPACTS,
        'timezone': _zone(),
        'channels': {'email': email_configured(config), 'matrix': matrix_configured(config)},
    })


# --- who gets it, and what they read -------------------------------------------------

@notif_bp.route('/admin/notifications/audience', methods=['POST'])
@login_required
@admin_required
def preview_audience():
    """Who would get {kind, params} now, and how; nothing is saved."""
    recipients = audience.recipients(_transient(_json()))
    return jsonify({'summary': _audience_summary(recipients),
                    'recipients': [_recipient_dict(r) for r in recipients]})


@notif_bp.route('/admin/notifications/preview', methods=['POST'])
@login_required
@admin_required
def preview_message():
    """{kind, params, subject, body, user_uid?, phase?} as one recipient would read it."""
    data = _json()
    notification = _transient(data)
    recipients = audience.recipients(notification)
    chosen = next((r for r in recipients if r.user_uid == data.get('user_uid')), None)
    if chosen is None:
        chosen = next((r for r in recipients if not r.unreachable), None) or \
            (recipients[0] if recipients else _me_as_recipient(notification.kind))
    return jsonify({
        'recipients': [{'user_uid': r.user_uid, 'username': r.username, 'unreachable': r.unreachable}
                       for r in recipients],
        'user_uid': chosen.user_uid,
        'username': chosen.username,
        **_message(notification, chosen, 'reminder' if data.get('phase') == 'reminder' else 'notice'),
    })


@notif_bp.route('/admin/notifications/test', methods=['POST'])
@login_required
@admin_required
def send_test():
    """Send {kind, params, subject, body} to the admin, written as for user_uid (or the first recipient)."""
    data = _json()
    notification = _transient(data)
    recipients = audience.recipients(notification)
    as_whom = next((r for r in recipients if r.user_uid == data.get('user_uid')), None) or \
        (recipients[0] if recipients else _me_as_recipient(notification.kind))
    me = _me_as_recipient(notification.kind)
    subject, body = render.render(notification, as_whom, current_app.config)
    message = render.finish(notification, f"[Test] {subject}", body, current_app.config)
    results = dispatch.send_directly(me.email, me.settings, message)
    if not results:
        return jsonify({'message': "No channel reaches you. Check your own settings.", 'results': []}), 400
    return jsonify({'as_user': as_whom.username, 'results': results})


# --- drafts, schedule, cancel ------------------------------------------------------

def _apply(notification, data, strict):
    """Copy the composer's fields onto ``notification``; strict for anything to be sent."""
    zone = _zone()
    if 'kind' in data:
        if data['kind'] not in compose.COMPOSABLE:
            raise ComposeError(f"kind is one of {', '.join(compose.COMPOSABLE)}.")
        notification.kind = data['kind']
    if 'subject' in data:
        subject = data['subject'] or ''
        if len(subject) > 255:
            raise ComposeError("Keep the subject under 255 characters.")
        notification.subject = subject
    if 'body' in data:
        notification.body = data['body'] or ''
    if 'params' in data or 'kind' in data:
        raw = data.get('params', notification.params_dict)
        try:
            notification.params_dict = compose.clean_params(notification.kind, raw, zone)
        except ComposeError:
            if strict:
                raise
            # A draft may be half done; it is checked again when scheduled.
            notification.params_dict = raw if isinstance(raw, dict) else {}
    for field in ('send_at', 'remind_at'):
        if field in data:
            setattr(notification, field, compose.parse_time(data[field], zone))


def _schedule_checks(notification):
    notification.params_dict = compose.clean_params(notification.kind, notification.params_dict, _zone())
    compose.check_ready(notification, _now())
    notification.notice_until = compose.notice_until(notification.kind, notification.params_dict)


@notif_bp.route('/admin/notifications', methods=['GET'])
@login_required
@admin_required
def list_notifications():
    kind = request.args.get('kind')
    query = db.select(Notification).order_by(Notification.created_at.desc(), Notification.id.desc())
    query = query.where(Notification.kind == kind) if kind else query.where(Notification.kind != 'expiry')
    return jsonify([_summary(n) for n in db.session.scalars(query.limit(200))])


@notif_bp.route('/admin/notifications', methods=['POST'])
@login_required
@admin_required
def create_draft():
    data = _json()
    if data.get('kind') not in compose.COMPOSABLE:
        raise ComposeError(f"kind is one of {', '.join(compose.COMPOSABLE)}.")
    notification = Notification(kind=data['kind'], status='draft', created_by=current_user.get_id())
    _apply(notification, data, strict=False)
    db.session.add(notification)
    db.session.commit()
    return jsonify(_summary(notification)), 201


def _get(notification_id):
    notification = db.get_or_404(Notification, notification_id)
    if notification.kind == 'expiry':
        raise ComposeError("Expiry reminders are sent by WhaP itself.")
    return notification


@notif_bp.route('/admin/notifications/<int:notification_id>', methods=['GET'])
@login_required
@admin_required
def get_notification(notification_id):
    return jsonify(_summary(db.get_or_404(Notification, notification_id)))


@notif_bp.route('/admin/notifications/<int:notification_id>', methods=['PUT'])
@login_required
@admin_required
def update_notification(notification_id):
    notification = _get(notification_id)
    if notification.status not in EDITABLE:
        return jsonify({'message': f"A {notification.status} notification can't be changed."}), 409
    scheduled = notification.status == 'scheduled'
    _apply(notification, _json(), strict=scheduled)
    if scheduled:
        _schedule_checks(notification)
    db.session.commit()
    return jsonify(_summary(notification))


@notif_bp.route('/admin/notifications/<int:notification_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_notification(notification_id):
    notification = _get(notification_id)
    if notification.status not in ('draft', 'cancelled'):
        return jsonify({'message': "Only drafts and cancelled notifications can be deleted."}), 409
    db.session.delete(notification)
    db.session.commit()
    return '', 204


@notif_bp.route('/admin/notifications/<int:notification_id>/schedule', methods=['POST'])
@login_required
@admin_required
def schedule(notification_id):
    """Schedule a draft: {send_at?, remind_at?}; no send_at means now."""
    notification = _get(notification_id)
    if notification.status != 'draft':
        return jsonify({'message': f"Only a draft can be scheduled; this one is {notification.status}."}), 409
    data = request.get_json(silent=True) or {}
    _apply(notification, {k: data[k] for k in ('send_at', 'remind_at') if k in data}, strict=True)
    now = _now()
    send_at = notification.send_at
    if send_at is None or (send_at.replace(tzinfo=UTC) if send_at.tzinfo is None else send_at) < now:
        notification.send_at = now
    _schedule_checks(notification)
    notification.status = 'scheduled'
    db.session.commit()
    current_app.logger.info(f"{current_user.get_id()} scheduled notification {notification.id} "
                            f"for {notification.send_at}")
    return jsonify(_summary(notification))


@notif_bp.route('/admin/notifications/<int:notification_id>/cancel', methods=['POST'])
@login_required
@admin_required
def cancel(notification_id):
    notification = _get(notification_id)
    if notification.status != 'scheduled':
        return jsonify({'message': f"Only a scheduled notification can be cancelled; this one is "
                                   f"{notification.status}."}), 409
    notification.status = 'cancelled'
    db.session.commit()
    return jsonify(_summary(notification))


# --- after sending ----------------------------------------------------------------

@notif_bp.route('/admin/notifications/<int:notification_id>/deliveries', methods=['GET'])
@login_required
@admin_required
def deliveries(notification_id):
    notification = db.get_or_404(Notification, notification_id)
    rows = db.session.scalars(
        db.select(NotificationDelivery).where(NotificationDelivery.notification_id == notification.id)
        .order_by(NotificationDelivery.status.desc(), NotificationDelivery.user_uid,
                  NotificationDelivery.channel)).all()
    local_ids = [int(d.user_uid.split(':', 1)[1]) for d in rows if d.user_uid.startswith('local:')]
    local_names = dict(db.session.execute(
        db.select(LocalUser.id, LocalUser.username).where(LocalUser.id.in_(local_ids))).all())

    def username(uid):
        prefix, ident = uid.split(':', 1)
        return local_names.get(int(ident), uid) if prefix == 'local' else ident

    return jsonify([{**d.to_dict(), 'username': username(d.user_uid)} for d in rows])


@notif_bp.route('/admin/notifications/<int:notification_id>/retry', methods=['POST'])
@login_required
@admin_required
def retry(notification_id):
    """Try the failed deliveries again: three more attempts each."""
    notification = db.get_or_404(Notification, notification_id)
    failed = db.session.scalars(db.select(NotificationDelivery).where(
        NotificationDelivery.notification_id == notification.id, NotificationDelivery.status == 'failed')).all()
    for delivery in failed:
        delivery.status = 'pending'
        delivery.attempts = 0
        delivery.next_attempt_at = None
    db.session.commit()
    return jsonify({'retrying': len(failed)})


@notif_bp.route('/admin/notifications/<int:notification_id>/copy', methods=['POST'])
@login_required
@admin_required
def copy(notification_id):
    """A new draft from this one: {follow_up: true} keeps who and what about, but not the text."""
    original = _get(notification_id)
    follow_up = bool((request.get_json(silent=True) or {}).get('follow_up'))
    draft = Notification(kind=original.kind, status='draft', created_by=current_user.get_id(),
                         params=original.params)
    if follow_up:
        draft.subject = f"Update: {original.subject}"
        draft.body = "Hello {name},\n\n"
    else:
        draft.subject, draft.body = original.subject, original.body
    db.session.add(draft)
    db.session.commit()
    return jsonify(_summary(draft)), 201
