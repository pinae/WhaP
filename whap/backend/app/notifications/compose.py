"""What an admin's notification may say and contain, before it is sent.

Templates to start from per kind, the checks on each kind's fields, and when
it is sent. Times come from the composer as local times in TIMEZONE (or with
an offset) and are kept as UTC.
"""
from datetime import datetime, UTC
from zoneinfo import ZoneInfo

from .. import db
from ..models import ComputeServer, Group

COMPOSABLE = ('maintenance', 'image', 'dataset', 'group', 'announcement')

IMPACTS = {
    'stopped': "your containers are stopped before the restart. Start them again in WhaP afterwards; "
               "files in your home directory are kept, running processes are not.",
    'restarted': "your containers restart by themselves afterwards; running processes are lost.",
    'none': "nothing; your containers keep running but may be slower.",
}

TEMPLATES = {
    'maintenance': {
        'subject': "{server} restarts on {start}",
        'body': "Hello {name},\n\n"
                "the compute server {server} will be restarted.\n\n"
                "When: {start} – {end} ({timezone})\n"
                "What happens: {impact}\n\n"
                "Your containers there:\n{containers}\n\n"
                "Please save your work and checkpoint long-running jobs before {start}.",
    },
    'image': {
        'subject': "A new version of {image}",
        'body': "Hello {name},\n\n"
                "a new version of the image {image} is available.\n\n"
                "What changed: ...\n\n"
                "Your containers keep the version they were created with. To use the new one, "
                "create a new container in the same project.\n\n"
                "Your containers with this image:\n{containers}",
    },
    'dataset': {
        'subject': "New data in {dataset}",
        'body': "Hello {name},\n\n"
                "the dataset {dataset} has new data: ...\n\n"
                "Your containers that mount it:\n{containers}",
    },
    'group': {'subject': "", 'body': "Hello {name},\n\n"},
    'announcement': {'subject': "", 'body': "Hello {name},\n\n"},
}

# The fields each kind's template can use, for the composer's "Insert" chips.
FIELDS = {
    'maintenance': ['name', 'server', 'start', 'end', 'timezone', 'impact', 'containers'],
    'image': ['name', 'image', 'containers'],
    'dataset': ['name', 'dataset', 'containers'],
    'group': ['name', 'group', 'containers'],
    'announcement': ['name', 'containers'],
}


class ComposeError(ValueError):
    """A notification that can't be saved or sent as it is; the message says why."""


def parse_time(value, zone):
    """A time from the composer as an aware UTC datetime; naive times are in ``zone``."""
    if value in (None, ''):
        return None
    try:
        moment = datetime.fromisoformat(value) if isinstance(value, str) else value
    except ValueError:
        raise ComposeError(f"'{value}' is not a date and time.")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo(zone))
    return moment.astimezone(UTC)


def _ids(value, model, what):
    if not isinstance(value, list) or not value or not all(isinstance(i, int) for i in value):
        raise ComposeError(f"Choose at least one {what}.")
    found = set(db.session.scalars(db.select(model.id).where(model.id.in_(value))))
    missing = sorted(set(value) - found)
    if missing:
        raise ComposeError(f"No {what} with id {', '.join(map(str, missing))}.")
    return sorted(set(value))


def clean_params(kind, params, zone):
    """``params`` for ``kind``, checked and normalised; raises ComposeError."""
    params = params or {}
    if not isinstance(params, dict):
        raise ComposeError("params must be an object.")
    if kind == 'maintenance':
        server_ids = _ids(params.get('server_ids'), ComputeServer, 'server')
        start, end = parse_time(params.get('start'), zone), parse_time(params.get('end'), zone)
        if not start or not end:
            raise ComposeError("Give the start and end of the maintenance.")
        if end <= start:
            raise ComposeError("The maintenance must end after it starts.")
        impact = params.get('impact') or 'stopped'
        if impact not in IMPACTS:
            raise ComposeError(f"impact is one of {', '.join(IMPACTS)}.")
        return {'server_ids': server_ids, 'start': start.isoformat(), 'end': end.isoformat(), 'impact': impact}
    if kind in ('image', 'dataset'):
        value = (params.get(kind) or '').strip()
        if not value:
            raise ComposeError(f"Choose the {kind}.")
        return {kind: value}
    if kind == 'group':
        return {'group_ids': _ids(params.get('group_ids'), Group, 'group')}
    if kind == 'announcement':
        return {}
    raise ComposeError(f"kind is one of {', '.join(COMPOSABLE)}.")


def check_ready(notification, now):
    """Raise ComposeError unless ``notification`` can be scheduled."""
    if not notification.subject.strip():
        raise ComposeError("Write a subject.")
    if not notification.body.strip():
        raise ComposeError("Write a message.")
    send_at = notification.send_at
    if send_at is not None and send_at.tzinfo is None:
        send_at = send_at.replace(tzinfo=UTC)
    remind_at = notification.remind_at
    if remind_at is not None and remind_at.tzinfo is None:
        remind_at = remind_at.replace(tzinfo=UTC)
    if remind_at is not None and remind_at <= (send_at or now):
        raise ComposeError("The reminder must come after the notification.")
    if notification.kind == 'maintenance' and remind_at is not None:
        start = datetime.fromisoformat(notification.params_dict['start'])
        if remind_at >= start:
            raise ComposeError("The reminder must come before the maintenance starts.")


def notice_until(kind, params):
    """Until when WhaP shows the notice on users' container pages."""
    if kind == 'maintenance':
        return datetime.fromisoformat(params['end'])
    return None
