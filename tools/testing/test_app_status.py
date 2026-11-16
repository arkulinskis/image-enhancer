"""Tests for the admin status report (AppStatus.py) and the admin_emails App Secret (AdminAccess.py).

    python tools/testing/test_app_status.py      -> prints ALL OK, or the first failure

Self-contained (only the users + error_log tables), the same file in every app (APP_MAKER/tools/app_status_rollout.py).
"""
import datetime as dt
import importlib
import json
import os
import pathlib
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
_tmp = pathlib.Path(tempfile.mkdtemp())
shutil.copytree(PROJECT / "server_code", _tmp / "app")
(_tmp / "app" / "__init__.py").write_text("")
if (PROJECT / "anvil.yaml").exists():  # git apps; source-layout apps take the schema from tools/sync_to_anvil.py
    os.environ["ANVIL_APP_YAML"] = str(PROJECT / "anvil.yaml")
sys.path[:0] = [str(HERE / "mock"), str(_tmp)]
import anvil.secrets  # noqa: E402
import anvil.server  # noqa: E402
import anvil.users  # noqa: E402
from anvil.tables import app_tables as T  # noqa: E402

AdminAccess = importlib.import_module("app.AdminAccess")
AppStatus = importlib.import_module("app.AppStatus")
now = dt.datetime.now(dt.timezone.utc)


def as_user(row):
    anvil.users.CURRENT[0] = row
    if hasattr(anvil.server.session, "use"):
        anvil.server.session.use(row.get_id() if row is not None else None)
    else:  # older mocks: one session object; start a fresh one per person
        anvil.server.session._d = {}


def call(name, *args):
    if hasattr(anvil.server, "call"):
        r = anvil.server.call(name, *args)
    else:  # older mocks have no registry: call the module function (its own admin check still runs)
        r = getattr(AppStatus, name)(*args)
    json.dumps(r)  # the reply must be JSON, like the browser needs
    return r


def denied(name, *args):
    try:
        call(name, *args)
    except anvil.server.PermissionDenied:
        return True
    return False


def person(email, admin=False, **kw):
    return T.users.add_row(email=email, enabled=True, signed_up=now - dt.timedelta(days=2), is_admin=admin, **kw)


# ---- the secret decides who may be promoted; the address itself is nowhere in the code
anvil.secrets.SECRETS.pop("admin_emails", None)
boss = person("Boss@Example.com")
anvil.server.get_app_origin = lambda *a: "https://app-test.anvil.app"  # hosted, whatever the mock says
assert not AdminAccess.may_promote(boss), "no secret -> nobody is promoted automatically"
anvil.secrets.SECRETS["admin_emails"] = "boss@example.com, second@example.com"
assert "boss@example.com" in AdminAccess.ADMIN_EMAILS and len(AdminAccess.ADMIN_EMAILS) == 2
assert AdminAccess.may_promote(boss), "listed + Google-style account (no password) -> promoted"
squatter = person("second@example.com", password_hash="x", confirmed_email=False)
assert not AdminAccess.may_promote(squatter), "someone who signed up first with the admin's address is NOT promoted"
squatter["confirmed_email"] = True
assert AdminAccess.may_promote(squatter), "a confirmed address counts"
assert not AdminAccess.may_promote(person("ana@example.com")), "unlisted -> no"
squatter["confirmed_email"] = False
_origin = anvil.server.get_app_origin
anvil.server.get_app_origin = lambda *a: "http://localhost:3031"
assert AdminAccess.may_promote(squatter), "the local App Server (Docker UI tests) promotes email + password accounts"
anvil.server.get_app_origin = lambda *a: "https://app-test.anvil.app"
assert not AdminAccess.may_promote(squatter)
import re  # noqa: E402
for f in (PROJECT / "server_code").rglob("*.py"):
    assert not re.search(r"ADMIN_EMAILS\s*=\s*[\[{(]\s*['\"][^'\"]*@", f.read_text(encoding="utf-8")),         "an admin address is written in %s: use the admin_emails App Secret" % f.name

if not hasattr(T, "list_columns") and not hasattr(anvil.server, "CALLABLES"):
    if not hasattr(T.users, "list_columns"):  # pre-2026 mock (fixed schema, bare rows): the report needs the real one
        print("ALL OK (app status: admin secret only; this app's old test mock can't run the report)")
        sys.exit(0)

# ---- the report: admins only
admin = person("boss2@example.com", admin=True)
ana = person("ana2@example.com")
as_user(None)
assert denied("admin_status_report"), "signed out -> no report"
as_user(ana)
assert denied("admin_status_report"), "members -> no report"
as_user(admin)
rep = call("admin_status_report")
assert rep["users"]["total"] >= 4 and rep["users"]["admins"] >= 1, rep["users"]
assert rep["users"]["signed_up"]["7d"] >= 4
assert rep["database"]["per_table"]["users"]["rows"] >= 4 and rep["database"]["total_rows"] >= 4
assert rep["app"]["admin_emails_secret"] == "set"
assert rep["errors"]["available"] and rep["errors"]["stored"] == 0

# ---- browser errors: anyone may report (signed out too), capped per session, trimmed
as_user(None)
assert call("log_client_error", "TypeError", "x" * 5000, "line 1\nline 2", "/#/home") is True
as_user(ana)
assert call("log_client_error", "KeyError", "'missing'", None, "/#/item/3") is True
row = T.error_log.search()[0]
assert len(row["message"]) == 1000 and row["source"] == "browser"
for _ in range(AppStatus.PER_SESSION_LIMIT + 5):
    call("log_client_error", "Spam", "again", None, "/")
spam = len([r for r in T.error_log.search() if r["kind"] == "Spam"])
assert spam == AppStatus.PER_SESSION_LIMIT - 1, "one session can't flood the table (%d)" % spam
as_user(admin)
rep = call("admin_status_report", 5)
e = rep["errors"]
assert e["last_24h"] == e["stored"] == AppStatus.PER_SESSION_LIMIT + 1 and len(e["recent"]) == 5
assert e["users_with_errors_7d"] == 1 and e["top_7d"][0]["kind"] == "Spam"
assert any(r["user"] == "ana2@example.com" for r in call("admin_status_report", 200)["errors"]["recent"])

# ---- the web address: admins only
endpoint = anvil.server.ENDPOINTS["/admin/status"]
as_user(ana)
assert endpoint().status == 403
as_user(None)
assert endpoint().status == 401, "signed out -> 401 (sign in first)"
as_user(admin)
resp = endpoint(errors="3")
assert resp.status == 200 and len(json.loads(resp.body)["errors"]["recent"]) == 3

# ---- Addanapp's signed requests (a throwaway TEST key; the real public key is in AppStatus.py)
import hashlib as _h, secrets as _s, time as _t  # noqa: E402
TEST_N = int("de78dda1006a64188f473b5d2c370a20a07f15b1cd7c50756faa222c283e79970ef521627b96f1ee0493281d13692665a8a014dbff6bfd824606aec1e3df7511f4479d8d5aaf1f7523c25d43f4a38c93a03dff8d105b978f736acb580205330f109527d11402c84f5e1e755f64d086952b80a0bc7f40383eab4380a92709553f", 16)
TEST_D = int("b08b0b9d633e0a56af04a0e84c591511552be46467a37a19e75604ae33f577f9d6e5d1eb5c1629c06f22f41736bb1fbc56774a76569834e1b77e401a1f21c9bccd0dbe29697deb59e67d2edaa8d4683548059992a3203fd800c41d3affe260a250fcdfdada264d641615277e2612c488f5dd1ea17ae9c23c9c7352b399841b91", 16)


def addanapp_headers(host, ts=None, n=TEST_N, d=TEST_D):
    ts, nonce = str(int(ts or _t.time())), _s.token_hex(8)
    size = (n.bit_length() + 7) // 8
    digest = _h.sha256(AppStatus.signature_message(host, ts, nonce).encode()).digest()
    em = b"\x00\x01" + b"\xff" * (size - 3 - 19 - 32) + b"\x00" + AppStatus._SHA256_PREFIX + digest
    sig = pow(int.from_bytes(em, "big"), d, n)
    return {"Host": host, "X-Addanapp-Ts": ts, "X-Addanapp-Nonce": nonce, "X-Addanapp-Sig": format(sig, "x")}


host = "app-test.anvil.app"
assert AppStatus.signed_by_addanapp(addanapp_headers(host), n=TEST_N)
assert not AppStatus.signed_by_addanapp(addanapp_headers(host), n=AppStatus.SIGNING_KEY_N), "other key -> no"
assert not AppStatus.signed_by_addanapp(addanapp_headers(host, ts=_t.time() - 3600), n=TEST_N), "old -> no"
other = addanapp_headers("other-app.anvil.app")
other["Host"] = host
assert not AppStatus.signed_by_addanapp(other, n=TEST_N), "signed for another app -> no"
bad = addanapp_headers(host)
bad["X-Addanapp-Sig"] = bad["X-Addanapp-Sig"][:-1] + ("0" if bad["X-Addanapp-Sig"][-1] != "0" else "1")
assert not AppStatus.signed_by_addanapp(bad, n=TEST_N), "tampered -> no"
assert not AppStatus.signed_by_addanapp({}, n=TEST_N)
real = AppStatus.SIGNING_KEY_N
AppStatus.SIGNING_KEY_N = TEST_N
as_user(None)
anvil.server.request.headers = addanapp_headers(host)
resp = endpoint()
assert resp.status == 200 and json.loads(resp.body)["users"]["total"] >= 4, "Addanapp gets the report signed out"
anvil.server.request.headers = {}
assert endpoint().status == 401
AppStatus.SIGNING_KEY_N = real

# ---- the secret alone is enough: opening the report ticks is_admin for a listed (proven) address
listed = person("second@example.com".replace("second", "third"))
anvil.secrets.SECRETS["admin_emails"] = "boss@example.com, third@example.com"
as_user(listed)
assert call("admin_status_report")["users"]["total"] >= 4 and listed["is_admin"] is True

# ---- permission flags: only log_client_error is open to everyone
if hasattr(anvil.server, "CALLABLES"):
    assert anvil.server.CALLABLES["admin_status_report"][1]
    assert not anvil.server.CALLABLES["log_client_error"][1]
print("ALL OK (app status)")
