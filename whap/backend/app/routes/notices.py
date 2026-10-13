"""What WhaP shows a user above their containers: maintenance on their servers,
and local projects about to expire. Read from the same records the senders
use, so it also reaches users who turned notifications off."""
from datetime import datetime, timedelta, UTC

from flask import Blueprint, current_app, jsonify
from flask_login import current_user, login_required

from .. import db
from ..models import ContainerInstance, Notification
from ..notifications import expiry, render
from ..notifications.compose import IMPACTS

notice_bp = Blueprint('notices', __name__)


def _aware(value):
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


@notice_bp.route('/notices', methods=['GET'])
@login_required
def my_notices():
    now = datetime.now(UTC)
    config = current_app.config
    zone = config.get('TIMEZONE') or 'UTC'
    mine = db.session.scalars(
        db.select(ContainerInstance).filter_by(**current_user.get_container_user_dict())
        .where(ContainerInstance.status != 'DELETED')).all()

    notices = []
    maintenance = db.session.scalars(
        db.select(Notification).where(Notification.kind == 'maintenance',
                                      Notification.status.in_(('scheduled', 'sending', 'sent')),
                                      Notification.notice_until > now)
        .order_by(Notification.notice_until)).all()
    for notification in maintenance:
        params = notification.params_dict
        affected = [c for c in mine if c.compute_server_id in (params.get('server_ids') or [])]
        if not affected:
            continue
        common = render.common_fields(notification, config)
        notices.append({
            'kind': 'maintenance', 'id': notification.id,
            'title': ' '.join(render.fill(notification.subject, common).split()),
            'servers': common['server'], 'start': common.get('start'), 'end': common.get('end'),
            'impact': IMPACTS.get(params.get('impact'), ''),
            'containers': sorted({c.project.name for c in affected if c.project}),
        })

    within = timedelta(days=max(expiry.steps()))
    for container in sorted((c for c in mine if expiry.is_local(c.image_name) and c.ttl_date
                             and now < _aware(c.ttl_date) <= now + within), key=lambda c: _aware(c.ttl_date)):
        fields = render.expiry_fields(expiry.notification_for(container, None).params_dict, zone, '')
        notices.append({
            'kind': 'expiry', 'container_id': container.id, 'project': fields['project'],
            'server': fields['server'], 'ttl_date': fields['ttl_date'], 'expires_in': fields['expires_in'],
            'urgent': _aware(container.ttl_date) - now <= timedelta(days=1),
        })
    return jsonify(notices)
