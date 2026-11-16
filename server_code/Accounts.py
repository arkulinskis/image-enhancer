"""Who is signed in, their profile, and who is an admin.

The emails in the App Secret `admin_emails` become admins the first time they sign in with a proven
address (Google sign-in or a confirmed email): see AdminAccess.py. The address is never in the code.
"""
import anvil.server
import anvil.users

from . import common as C
from . import AdminAccess

ADMIN_EMAILS = AdminAccess.ADMIN_EMAILS  # from the App Secret `admin_emails`


def me_dict(user):
    if user is None:
        return None
    return {"id": user.get_id(), "email": user["email"], "name": C.name_of(user),
            "is_admin": C.is_admin(user), "joined": C.iso(user["signed_up"])}


@anvil.server.callable
def get_me():
    """The signed-in user (or None). Called when the app starts and after signing in."""
    user = anvil.users.get_user()
    if user is None:
        return None
    changes: dict = {}
    if AdminAccess.may_promote(user) and not user["is_admin"]:
        changes["is_admin"] = True
    seen = user["last_seen"]
    if seen is None or (C.now() - seen).total_seconds() > 3600:
        changes["last_seen"] = C.now()
    if changes:
        user.update(**changes)
    return me_dict(user)


@anvil.server.callable(require_user=True)
def update_profile(name):
    user = C.require_user()
    name = C.text(name, 60)
    if len(name) < 2:
        return C.fail("Please use at least 2 characters for your name.")
    user["display_name"] = name
    return C.ok(me=me_dict(user))
