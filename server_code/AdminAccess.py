"""Who becomes an admin automatically: the emails in the App Secret `admin_emails` (APP_MAKER standard, 2026-11-16).

The admin's email is never written in the code (the code is public on GitHub). Set it once per app in the Anvil
editor: App Secrets -> Create secret -> name `admin_emails`, value `you@example.com` (several: comma-separated).
No secret = nobody is promoted automatically; people who already have `is_admin` ticked keep it.

    ADMIN_EMAILS              set-like: `email in ADMIN_EMAILS`, `for e in ADMIN_EMAILS`, `sorted(ADMIN_EMAILS)`
    may_promote(user)         listed email AND the address is proven (Google sign-in or a confirmed email)

Why "proven": email confirmation is off in these apps, so without that check anyone could sign up first with the
admin's address (in an app the admin hasn't joined yet) and become an admin. Google accounts have no password and
are verified by Google; email + password accounts count once `confirmed_email` is ticked. For your own email +
password account, sign in with Google once or tick `is_admin` in the users table.
Same file in every app: APP_MAKER/template-forms/server_code/AdminAccess.py (tools/app_status_rollout.py copies it).
"""
import re

import anvil.secrets

SECRET = "admin_emails"


def admin_emails():
    try:
        raw = anvil.secrets.get_secret(SECRET) or ""
    except Exception:
        return frozenset()
    return frozenset(e.strip().lower() for e in re.split(r"[,;\s]+", str(raw)) if "@" in e)


class _Emails(object):
    """Read from the secret at use time, so tests and a changed secret need no import-time setup."""

    def __contains__(self, email):
        return isinstance(email, str) and email.strip().lower() in admin_emails()

    def __iter__(self):
        return iter(sorted(admin_emails()))

    def __len__(self):
        return len(admin_emails())

    def __bool__(self):
        return bool(admin_emails())

    def __repr__(self):
        return "<admin_emails secret: %d address(es)>" % len(admin_emails())


ADMIN_EMAILS = _Emails()


def _col(user, name):
    try:
        return user[name]
    except Exception:
        return None


def _local_app_server():
    """The Anvil App Server on this PC (Docker UI tests): its origin is http://localhost:<port>. Hosted Anvil apps are
    always https://..., and the origin is the app's own setting, not something a visitor can send."""
    try:
        import anvil.server
        origin = str(anvil.server.get_app_origin() or "")
    except Exception:
        return False
    return origin.startswith(("http://localhost:", "http://127.0.0.1:"))


def verified(user):
    """The account's email is proven: confirmed, or a Google account (no password). Local test server: any account."""
    if user is None:
        return False
    return bool(_col(user, "confirmed_email")) or not _col(user, "password_hash") or _local_app_server()


def may_promote(user):
    return user is not None and (_col(user, "email") or "") in ADMIN_EMAILS and verified(user)
