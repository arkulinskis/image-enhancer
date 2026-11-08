"""anvil.users for the tests and the dev server.

CURRENT[0] is the signed-in user row (or None). PASSWORDS maps email -> password for login_with_email.
The dev server keeps one CURRENT per browser session and swaps it in before each call.
"""
import datetime as _dt

CURRENT = [None]
PASSWORDS = {}


class AuthenticationFailed(Exception): pass
class UserExists(AuthenticationFailed): pass
class EmailNotConfirmed(AuthenticationFailed): pass
class AccountIsNotEnabled(AuthenticationFailed): pass
class TooManyPasswordFailures(AuthenticationFailed): pass
class PasswordNotAcceptable(AuthenticationFailed): pass
class MFARequired(AuthenticationFailed): pass


def get_user(allow_remembered=True):
    return CURRENT[0]


def force_login(user, remember=False):
    CURRENT[0] = user


def logout():
    CURRENT[0] = None


def _users():
    from anvil.tables import app_tables
    return app_tables.users


def login_with_email(email, password, remember=False):
    row = _users().get(email=(email or "").strip().lower())
    if row is None or PASSWORDS.get(row["email"]) != password:
        raise AuthenticationFailed("Incorrect email address or password")
    if row["enabled"] is False:
        raise AccountIsNotEnabled("This account has not been enabled by an administrator")
    CURRENT[0] = row
    return row


def signup_with_email(email, password, remember=False):
    email = (email or "").strip().lower()
    if "@" not in email:
        raise AuthenticationFailed("Please enter a valid email address")
    if len(password or "") < 8:
        raise PasswordNotAcceptable("Your password must be at least 8 characters long")
    if _users().get(email=email) is not None:
        raise UserExists("This email address has already been registered for our service. Try logging in.")
    row = _users().add_row(email=email, enabled=True, signed_up=_dt.datetime.now(_dt.timezone.utc))
    PASSWORDS[email] = password
    CURRENT[0] = row
    return row


def send_password_reset_email(email):
    if _users().get(email=(email or "").strip().lower()) is None:
        raise AuthenticationFailed("No such user")
