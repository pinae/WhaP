"""Matrix messages from WhaP's bot account, over the client-server API."""
from urllib.parse import quote

import requests

from .errors import DeliveryError

TIMEOUT = 20


class MatrixChannel:
    """Talks to the homeserver in the app config as the bot account.

    The access token travels only in the Authorization header and never
    appears in an error message.
    """

    def __init__(self, config, session=None):
        self.base = (config.get('MATRIX_HOMESERVER_URL') or '').rstrip('/')
        self.token = config.get('MATRIX_ACCESS_TOKEN')
        self.http = session or requests.Session()

    @property
    def configured(self):
        return bool(self.base and self.token)

    def _request(self, method, path, body):
        if not self.configured:
            raise DeliveryError("Matrix is not configured: MATRIX_HOMESERVER_URL and MATRIX_ACCESS_TOKEN are not set.")
        try:
            response = self.http.request(method, f"{self.base}/_matrix/client/v3{path}", json=body,
                                         headers={'Authorization': f"Bearer {self.token}"}, timeout=TIMEOUT)
        except requests.RequestException as e:
            raise DeliveryError(f"Could not reach {self.base}: {type(e).__name__}")
        if response.ok:
            return response.json()
        try:
            error = response.json()
        except ValueError:
            error = {}
        reason = f"{response.status_code} {error.get('errcode', '')} {error.get('error', '')}".strip()
        # Rate limits and server trouble pass; anything else the homeserver
        # refused (not in the room, unknown user) will be refused again.
        temporary = response.status_code == 429 or response.status_code >= 500
        raise DeliveryError(f"The homeserver refused: {reason}", permanent=not temporary)

    def send(self, room_id, text, html=None, txn_id=None):
        """Post a message to a room. Retrying with the same ``txn_id`` cannot post it twice."""
        content = {'msgtype': 'm.text', 'body': text}
        if html:
            content.update(format='org.matrix.custom.html', formatted_body=html)
        path = f"/rooms/{quote(room_id, safe='')}/send/m.room.message/{quote(txn_id or 'whap', safe='')}"
        return self._request('PUT', path, content)['event_id']

    def create_direct_room(self, user_id):
        """Open a direct chat with ``user_id`` and invite them; returns the room id."""
        body = {'preset': 'trusted_private_chat', 'is_direct': True, 'invite': [user_id], 'name': 'WhaP'}
        return self._request('POST', '/createRoom', body)['room_id']

    def leave(self, room_id):
        """Leave a room, e.g. the chat with a user who disconnected."""
        self._request('POST', f"/rooms/{quote(room_id, safe='')}/leave", {})
