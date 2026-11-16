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
    anvil.server.session.use(row.get_id() if row is not None else None)


def call(name, *args):
    r = anvil.server.call(name, *args)
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
assert endpoint().status == 403
as_user(admin)
resp = endpoint(errors="3")
assert resp.status == 200 and len(json.loads(resp.body)["errors"]["recent"]) == 3

# ---- permission flags: only log_client_error is open to everyone
assert anvil.server.CALLABLES["admin_status_report"][1]
assert not anvil.server.CALLABLES["log_client_error"][1]
print("ALL OK (app status)")
