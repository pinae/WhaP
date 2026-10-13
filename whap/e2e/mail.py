"""What WhaP sent, read from Mailpit, which catches every mail on a rig with e2e enabled."""
import json
import time
import urllib.request


class Mailbox:
    def __init__(self, api):
        self.api = api

    def _call(self, method, path):
        request = urllib.request.Request(f"{self.api}{path}", method=method)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read()
        except OSError as e:
            raise AssertionError(f"Mailpit at {self.api} did not answer ({e}). Is the rig deployed with "
                                 "e2e enabled, and [mail] api in rig.toml right?") from e
        # Deleting answers a plain "ok"; everything read is JSON.
        return json.loads(body) if method == "GET" else None

    def clear(self):
        self._call("DELETE", "/api/v1/messages")

    def messages(self):
        """The newest messages first, as Mailpit lists them (without bodies)."""
        return self._call("GET", "/api/v1/messages?limit=200")["messages"]

    def wait_for(self, to, subject, timeout=90):
        """The first message to ``to`` whose subject contains ``subject``, with its Text and HTML.

        The worker checks for due notifications every 10 seconds, so allow for that.
        """
        deadline = time.monotonic() + timeout
        while True:
            for summary in self.messages():
                if subject in summary["Subject"] and any(a["Address"] == to for a in summary["To"]):
                    return self._call("GET", f"/api/v1/message/{summary['ID']}")
            if time.monotonic() > deadline:
                seen = [f"{m['Subject']} -> {', '.join(a['Address'] for a in m['To'])}" for m in self.messages()]
                raise AssertionError(f"No mail to {to} with '{subject}' in its subject within {timeout}s. "
                                     f"Mailpit has: {seen or 'nothing'}. Is the worker running?")
            time.sleep(2)
