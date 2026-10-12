class DeliveryError(Exception):
    """A message could not be delivered.

    ``permanent`` means trying again won't help (an unknown mailbox, a user who
    left the bot's chat); otherwise the delivery is retried later. The message
    is shown to admins in the delivery report, so it must never contain a
    password or token.
    """

    def __init__(self, message, permanent=False):
        super().__init__(message)
        self.permanent = permanent
