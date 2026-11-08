"""API keys: one per app that uses the service ("clients").

A key looks like `ie_<40 random characters>`. It is shown ONCE when made; the table keeps only its SHA-256 and the
first characters (to tell keys apart). Each key also gets a webhook secret, used to sign the "job finished" calls
this service makes to the app (HMAC-SHA256), so the app can check they really came from here.
Keys are sent in the `Authorization: Bearer ie_...` header, never in the address.
"""
import hashlib
import hmac
import secrets

import anvil.server
from anvil.tables import app_tables
import anvil.tables as tables
import anvil.tables.query as q

from . import common as C

PREFIX = "ie_"
DEFAULT_HOURLY = 60


def _hash(key):
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def new_key():
    return PREFIX + secrets.token_urlsafe(30).replace("-", "x").replace("_", "y")[:40]


def authenticate(token):
    """(client row, None) or (None, (http status, message))."""
    token = (token or "").strip()
    if not token:
        return None, (401, "Send your API key in the header: Authorization: Bearer ie_...")
    if not token.startswith(PREFIX) or len(token) < 20:
        return None, (401, "That isn't an Image Enhancer API key.")
    h = _hash(token)
    row = app_tables.clients.get(key_hash=h)
    if row is None or not hmac.compare_digest(row["key_hash"] or "", h):
        return None, (401, "Unknown API key. Make one on the Apps & keys page of the console.")
    if not row["active"]:
        return None, (403, "This API key is switched off. Switch it on again on the Apps & keys page.")
    stamp = C.now()
    if row["last_used"] is None or (stamp - row["last_used"]).total_seconds() > 60:
        row["last_used"] = stamp
    return row, None


def sign(secret, body_bytes):
    return "sha256=" + hmac.new((secret or "").encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()


def client_dict(r, counts=None):
    counts = counts or {}
    return {"id": r.get_id(), "name": r["name"], "prefix": r["key_prefix"], "active": bool(r["active"]),
            "hourly_limit": int(r["hourly_limit"] or DEFAULT_HOURLY), "note": r["note"] or "",
            "created": C.iso(r["created"]), "last_used": C.iso(r["last_used"]), "jobs_total": int(r["jobs_total"] or 0),
            "waiting": counts.get("waiting", 0), "demo": bool(r["is_demo"])}


def _issue(row):
    key, secret = new_key(), "whsec_" + secrets.token_urlsafe(24)
    row.update(key_hash=_hash(key), key_prefix=key[:9], webhook_secret=secret)
    return key, secret


@anvil.server.callable(require_user=True)
def keys_list():
    C.require_admin()
    waiting: dict = {}
    for j in app_tables.jobs.search(status=q.any_of("queued", "working")):
        if j["client"] is not None:
            waiting[j["client"].get_id()] = waiting.get(j["client"].get_id(), 0) + 1
    out = [client_dict(r, {"waiting": waiting.get(r.get_id(), 0)})
           for r in app_tables.clients.search(tables.order_by("created", ascending=False))]
    return {"clients": out}


@anvil.server.callable(require_user=True)
def key_create(name, hourly_limit=DEFAULT_HOURLY, note=""):
    C.require_admin()
    name = C.text(name, 60)
    if len(name) < 2:
        return C.fail("Name the app this key is for (at least 2 characters), e.g. Little Hero Books.")
    if app_tables.clients.get(name=name):
        return C.fail("There is already a key called “%s”. Pick another name." % name)
    try:
        limit = max(1, min(10000, int(hourly_limit or DEFAULT_HOURLY)))
    except (TypeError, ValueError):
        return C.fail("The hourly limit must be a whole number.")
    row = app_tables.clients.add_row(name=name, active=True, hourly_limit=limit, note=C.text(note, 300),
                                     created=C.now(), jobs_total=0, is_demo=False)
    key, secret = _issue(row)
    from . import Queue
    Queue.event("key", "New API key for %s" % name)
    return C.ok(client=client_dict(row), key=key, webhook_secret=secret)


@anvil.server.callable(require_user=True)
def key_update(client_id, name, hourly_limit, active, note=""):
    C.require_admin()
    row = C.row_by_id(app_tables.clients, client_id)
    if row is None:
        return C.fail("That key no longer exists.")
    name = C.text(name, 60)
    if len(name) < 2:
        return C.fail("Give it a name (at least 2 characters).")
    other = app_tables.clients.get(name=name)
    if other is not None and other != row:
        return C.fail("Another key already has that name.")
    try:
        limit = max(1, min(10000, int(hourly_limit)))
    except (TypeError, ValueError):
        return C.fail("The hourly limit must be a whole number.")
    row.update(name=name, hourly_limit=limit, active=bool(active), note=C.text(note, 300))
    return C.ok(client=client_dict(row))


@anvil.server.callable(require_user=True)
def key_rotate(client_id):
    """A new key and webhook secret for the same app; the old key stops working at once."""
    C.require_admin()
    row = C.row_by_id(app_tables.clients, client_id)
    if row is None:
        return C.fail("That key no longer exists.")
    key, secret = _issue(row)
    from . import Queue
    Queue.event("key", "New key issued for %s (the old one stopped working)" % row["name"])
    return C.ok(client=client_dict(row), key=key, webhook_secret=secret)


@anvil.server.callable(require_user=True)
def key_delete(client_id):
    """Delete the key. Its jobs stay in the history (shown as from a deleted app); waiting ones are cancelled."""
    C.require_admin()
    row = C.row_by_id(app_tables.clients, client_id)
    if row is None:
        return C.ok()
    for j in app_tables.jobs.search(client=row):
        if j["status"] in ("queued", "working"):
            j.update(status="cancelled", finished=C.now(), error="The app's API key was deleted.")
        j["client"] = None
    name = row["name"]
    row.delete()
    from . import Queue
    Queue.event("key", "Deleted the API key for %s" % name)
    return C.ok()
