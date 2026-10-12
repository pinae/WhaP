"""Send what is due, then exit. Started by worker.py, one at a time.

Exit status 75 (EX_TEMPFAIL) means LDAP could not be asked, so due
notifications are still waiting; the worker tries again a minute later.
"""
import sys

from app import create_app
from app.notifications import dispatch
from app.services.ldap_service import LdapUnavailable

MAX_ROUNDS = 50  # BATCH deliveries each; the worker starts another run if more is left
EX_TEMPFAIL = 75


def main():
    app = create_app()
    with app.app_context():
        for _ in range(MAX_ROUNDS):
            if not dispatch.work_due():
                return 0
            try:
                dispatch.run_once()
            except LdapUnavailable as e:
                print(f"Notifications wait for LDAP: {e}")
                return EX_TEMPFAIL
    return 0


if __name__ == '__main__':
    sys.exit(main())
