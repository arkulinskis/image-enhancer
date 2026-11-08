"""Privacy & Terms: records who accepted which version of the legal documents.

Installed from APP_MAKER/legal-kit/anvil/legal_server.py. Edit it there and re-run install.py.

Stores three columns on the users table:
  legal_version      the version accepted (the documents' date, e.g. "2026-10-26")
  legal_accepted_at  when (UTC)
  legal_source       "signup" (ticked on the sign-up form) or "page" (the "I agree" button)
The exact text of every version is kept in APP_MAKER/legal-kit/dist/<app>/<version>/.
"""
from datetime import datetime, timezone

import anvil.server
import anvil.users

VERSION = "2026-10-31"


def _get(row, col):
    try:
        return row[col]
    except Exception:  # column not created yet (schema not applied)
        return None


@anvil.server.callable
def legal_state():
    user = anvil.users.get_user()
    if user is None:
        return {"signedIn": False, "version": VERSION}
    at = _get(user, "legal_accepted_at")
    return {"signedIn": True, "version": VERSION,
            "accepted_version": _get(user, "legal_version"),
            "accepted_at": at.isoformat() if at else None,
            "email": _get(user, "email")}


@anvil.server.callable
def legal_accept(version, source="page"):
    user = anvil.users.get_user()
    if user is None:
        return {"ok": False, "error": "Please sign in first."}
    if version != VERSION:
        return {"ok": False, "error": "These documents have changed. Please reload the page."}
    source = source if source in ("signup", "page") else "page"
    now = datetime.now(timezone.utc)
    try:
        user.update(legal_version=VERSION, legal_accepted_at=now, legal_source=source)
    except Exception as e:
        print("legal_accept could not save:", repr(e))
        return {"ok": False, "error": "Could not save. Please try again later."}
    return {"ok": True, "accepted_version": VERSION, "accepted_at": now.isoformat()}
