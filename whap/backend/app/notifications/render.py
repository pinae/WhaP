"""What a notification says to one person: templates filled in, as text and HTML."""
import html
import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from .. import db
from ..models import ComputeServer, Group
from .compose import IMPACTS

FIELD = re.compile(r'\{(\w+)\}')
URL = re.compile(r'(https?://[^\s<>"]+[^\s<>".,;:!?)])')


def fill(template, fields):
    """Replace {field} with its value; unknown names stay as written."""
    return FIELD.sub(lambda m: str(fields[m.group(1)]) if m.group(1) in fields else m.group(0), template or '')


def format_time(value, zone, with_date=True):
    """'Tue 20 Oct, 08:00' (or '08:00') in ``zone``, from an ISO string or a datetime.

    A time without a zone is taken as already in ``zone``: the composer's
    local times, kept as typed in a draft that isn't complete yet.
    """
    if not value:
        return ''
    try:
        moment = datetime.fromisoformat(value) if isinstance(value, str) else value
    except ValueError:
        return str(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo(zone))
    local = moment.astimezone(ZoneInfo(zone))
    return local.strftime('%a %-d %b, %H:%M') if with_date else local.strftime('%H:%M')


def linkify(escaped):
    """Turn the URLs in already escaped text into links."""
    return URL.sub(lambda m: f'<a href="{m.group(1)}">{m.group(1)}</a>', escaped)


def text_to_html(text):
    """Plain text as simple HTML: paragraphs, line breaks, links."""
    paragraphs = re.split(r'\n\s*\n', (text or '').strip())
    rendered = []
    for paragraph in paragraphs:
        escaped = html.escape(paragraph)
        rendered.append('<p>' + linkify(escaped).replace('\n', '<br>\n') + '</p>')
    return '\n'.join(rendered)


def server_names(params):
    """The hostnames of a maintenance notification's servers, as they are named now."""
    ids = params.get('server_ids') or []
    if not ids:
        return ''
    names = db.session.scalars(db.select(ComputeServer.hostname).where(ComputeServer.id.in_(ids))
                               .order_by(ComputeServer.hostname)).all()
    return ', '.join(names)


def group_names(params):
    """The names of a group notification's WhaP groups."""
    ids = params.get('group_ids') or []
    if not ids:
        return ''
    return ', '.join(db.session.scalars(db.select(Group.name).where(Group.id.in_(ids)).order_by(Group.name)))


def container_lines(containers):
    return '\n'.join(f"  • {c.project.name if c.project else '?'} ({c.image_name}) on "
                     f"{c.compute_server.hostname if c.compute_server else '?'}" for c in containers)


def common_fields(notification, config):
    """The values that are the same for every recipient."""
    zone = config.get('TIMEZONE') or 'UTC'
    whap_url = (config.get('WHAP_URL') or '').rstrip('/')
    params = notification.params_dict
    fields = {
        'whap_url': whap_url,
        'settings_url': f"{whap_url}/settings" if whap_url else '',
        'image': params.get('image', ''),
        'dataset': params.get('dataset', ''),
        'server': server_names(params),
        'group': group_names(params),
        'timezone': zone,
        'impact': IMPACTS.get(params.get('impact'), ''),
    }
    start, end = params.get('start'), params.get('end')
    if start:
        fields['start'] = format_time(start, zone)
    if end:
        same_day = start and format_time(start, zone)[:10] == format_time(end, zone)[:10]
        fields['end'] = format_time(end, zone, with_date=not same_day)
    return fields


def fields_for(notification, recipient, config):
    """The values a template may use, for this notification and person."""
    return {**common_fields(notification, config), 'name': recipient.name, 'username': recipient.username,
            'containers': container_lines(recipient.containers)}


def why(notification):
    """The footer's first sentence: why this person got this message."""
    params = notification.params_dict
    return {
        'maintenance': f"You get this because you have containers on {server_names(params)}.",
        'image': f"You get this because you use the image {params.get('image', '')}.",
        'dataset': f"You get this because your containers mount the dataset {params.get('dataset', '')}.",
        'expiry': "You get this because you asked to be reminded before local containers expire.",
        'announcement': "WhaP sends announcements to everyone who uses it.",
        'group': f"You get this because you are a member of the WhaP group {group_names(params)}.",
    }[notification.kind]


@dataclass
class Message:
    subject: str
    text: str
    html: str


def finish(notification, subject, body, config):
    """The message as sent: the rendered subject and body plus the footer."""
    whap_url = (config.get('WHAP_URL') or '').rstrip('/')
    footer = why(notification)
    if whap_url:
        footer += f" Change what WhaP tells you: {whap_url}/settings"
    text = f"{body.rstrip()}\n\n-- \n{footer}\n"
    html_body = (text_to_html(body) +
                 f'\n<hr>\n<p style="color:#666;font-size:smaller">{linkify(html.escape(footer))}</p>')
    return Message(subject=subject, text=text, html=html_body)


def render(notification, recipient, config, phase='notice'):
    """(subject, body) for one recipient, before the footer is added."""
    fields = fields_for(notification, recipient, config)
    # One line: a line break in a mail header is refused (and would be header injection).
    subject = ' '.join(fill(notification.subject, fields).split())
    if phase == 'reminder':
        subject = f"Reminder: {subject}"
    return subject, fill(notification.body, fields)
