"""Email over SMTP: one connection for a batch of messages."""
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from .errors import DeliveryError

TIMEOUT = 30


def _smtp_error(e):
    """A DeliveryError for an SMTP failure: 5xx replies are permanent, the rest temporary."""
    if isinstance(e, smtplib.SMTPRecipientsRefused):
        codes = [code for code, _ in e.recipients.values()]
        detail = '; '.join(f"{code} {msg.decode(errors='replace') if isinstance(msg, bytes) else msg}"
                           for code, msg in e.recipients.values())
        return DeliveryError(f"Recipient refused: {detail}", permanent=all(code >= 500 for code in codes))
    if isinstance(e, smtplib.SMTPResponseException):
        message = e.smtp_error.decode(errors='replace') if isinstance(e.smtp_error, bytes) else e.smtp_error
        return DeliveryError(f"{e.smtp_code} {message}", permanent=e.smtp_code >= 500)
    return DeliveryError(f"{type(e).__name__}: {e}")


class EmailChannel:
    """Sends through the SMTP server in the app config.

    Use as a context manager; it connects (and logs in) on entry::

        with EmailChannel(config) as channel:
            channel.send("alice@example.org", "Subject", text, html)

    Connection and login failures raise DeliveryError (temporary): they are the
    server's or the configuration's fault, not the recipient's.
    """

    def __init__(self, config):
        self.server = config.get('SMTP_SERVER')
        self.port = int(config.get('SMTP_PORT') or 587)
        self.security = (config.get('SMTP_SECURITY') or 'starttls').lower()
        self.username = config.get('SMTP_USERNAME')
        self.password = config.get('SMTP_PASSWORD')
        self.sender = config.get('SENDER_EMAIL')
        self.sender_name = config.get('SENDER_NAME') or 'WhaP'
        self.ssl_context = ssl.create_default_context()
        self.smtp = None

    def __enter__(self):
        if not (self.server and self.sender):
            raise DeliveryError("Email is not configured: SMTP_SERVER and SENDER_EMAIL are not set.")
        try:
            if self.security == 'ssl':
                self.smtp = smtplib.SMTP_SSL(self.server, self.port, timeout=TIMEOUT, context=self.ssl_context)
            else:
                self.smtp = smtplib.SMTP(self.server, self.port, timeout=TIMEOUT)
                if self.security == 'starttls':
                    self.smtp.starttls(context=self.ssl_context)
            if self.username:
                self.smtp.login(self.username, self.password)
        except (smtplib.SMTPException, OSError) as e:
            self._close()
            # Not _smtp_error: a 535 for a wrong password is 5xx but must not
            # fail every delivery for good.
            raise DeliveryError(f"Could not connect to {self.server}:{self.port}: {type(e).__name__}: {e}")
        return self

    def __exit__(self, *exc):
        self._close()

    def _close(self):
        if self.smtp:
            try:
                self.smtp.quit()
            except (smtplib.SMTPException, OSError):
                pass
            self.smtp = None

    def message(self, to, subject, text, html=None):
        msg = EmailMessage()
        msg['From'] = formataddr((self.sender_name, self.sender))
        msg['To'] = to
        msg['Subject'] = subject
        msg['Date'] = formatdate(localtime=True)
        msg['Message-ID'] = make_msgid(domain=self.sender.rpartition('@')[2] or None)
        # A notification, not a person: no out-of-office replies (RFC 3834).
        msg['Auto-Submitted'] = 'auto-generated'
        msg['X-Auto-Response-Suppress'] = 'All'
        msg.set_content(text)
        if html:
            msg.add_alternative(html, subtype='html')
        return msg

    def send(self, to, subject, text, html=None):
        try:
            message = self.message(to, subject, text, html)
        except ValueError as e:  # e.g. a malformed address from the directory
            raise DeliveryError(f"Cannot write this message: {e}", permanent=True)
        try:
            self.smtp.send_message(message)
        except (smtplib.SMTPException, OSError) as e:
            raise _smtp_error(e)
