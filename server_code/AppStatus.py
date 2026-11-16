"""App status report for admins: users, database rows, errors, background tasks, health (APP_MAKER standard, 2026-11-16).

    In the app (signed-in admin):  anvil.server.call("admin_status_report")
    Web address (admins only):     https://<app address>/_/api/admin/status
        - open it in a browser tab where you are signed in to the app as an admin, or
        - from a script: HTTP Basic auth with an admin's email + password (Google-only accounts: use the browser).
        Anyone else gets 401/403 and no data. ?errors=50 shows more recent errors (max 200).

Errors come from the `error_log` table: the browser reports every uncaught error (session_guard.py ->
log_client_error), including server errors that reached the page, with the session, page and signed-in user.
Anvil's own App Logs (in the editor) stay the full record; this table keeps the newest KEEP_ERRORS rows.
Every section is optional: a table or column an app doesn't have is skipped, never an error.
Same file in every app: APP_MAKER/template-forms/server_code/AppStatus.py (tools/app_status_rollout.py copies it).
"""
import collections
import datetime as dt
import hashlib
import json
import random
import sys
import time
import typing

import anvil.server
import anvil.users
from anvil.tables import app_tables
import anvil.tables as tables

from . import AdminAccess

VERSION = "2026-11-16"
KEEP_ERRORS = 1000          # error_log keeps the newest rows only (data table rows count towards the plan)
PER_SESSION_LIMIT = 30      # browser error reports per session per hour


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _iso(v):
    if isinstance(v, dt.datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=dt.timezone.utc)
        return v.astimezone(dt.timezone.utc).isoformat()
    return v


def _aware(v):
    if isinstance(v, dt.datetime) and v.tzinfo is None:
        return v.replace(tzinfo=dt.timezone.utc)
    return v


def _admin(user):
    try:
        return bool(user is not None and user["is_admin"])
    except Exception:
        return False


def _require_admin():
    u = anvil.users.get_user()
    if u is None:
        raise anvil.server.PermissionDenied("Please sign in first.")
    if not _admin(u):
        raise anvil.server.PermissionDenied("Only admins can do that.")
    return u


def _table(name):
    try:
        return getattr(app_tables, name)
    except Exception:
        return None


def _table_names():
    try:
        names = [str(n) for n in typing.cast(typing.Any, app_tables)]
    except TypeError:
        names = [n for n in dir(app_tables) if not n.startswith("_") and hasattr(getattr(app_tables, n), "search")]
    return sorted(set(names))


def _columns(table):
    try:
        return {c["name"] for c in table.list_columns()}
    except Exception:
        return set()


def _session_tag():
    try:
        sid = anvil.server.get_session_id() or ""
    except Exception:
        sid = ""
    return hashlib.sha256(sid.encode()).hexdigest()[:10] if sid else ""


def _clip(v, n):
    return ("" if v is None else str(v))[:n]


# ------------------------------------------------------------------------------------------------ sections

def _users(now):
    t = _table("users")
    if t is None:
        return {"available": False}
    cols = _columns(t)
    rows = list(t.search())
    if "is_demo" in cols:
        rows = [u for u in rows if not u["is_demo"]]
    out = {"available": True, "total": len(rows)}
    if "is_admin" in cols:
        out["admins"] = sum(1 for u in rows if u["is_admin"])
    if "enabled" in cols:
        out["disabled"] = sum(1 for u in rows if u["enabled"] is False)
    if "password_hash" in cols:
        out["google_or_passwordless"] = sum(1 for u in rows if not u["password_hash"])
        out["email_password"] = len(rows) - out["google_or_passwordless"]
    if "confirmed_email" in cols:
        out["confirmed_email"] = sum(1 for u in rows if u["confirmed_email"])

    def window(col):
        if col not in cols:
            return None
        stamps = [_aware(u[col]) for u in rows if isinstance(u[col], dt.datetime)]
        res: typing.Dict[str, typing.Any] = {k: sum(1 for s in stamps if now - s <= dt.timedelta(days=d)) for k, d in
               (("24h", 1), ("7d", 7), ("30d", 30))}
        res["latest"] = _iso(max(stamps)) if stamps else None
        return res

    out["signed_up"] = window("signed_up")
    out["signed_in"] = window("last_login")
    out["active"] = window("last_seen")   # template apps stamp last_seen at most once an hour
    if out["signed_up"]:
        by_day = collections.Counter(_aware(u["signed_up"]).date().isoformat() for u in rows
                                     if isinstance(u["signed_up"], dt.datetime)
                                     and now - _aware(u["signed_up"]) <= dt.timedelta(days=30))
        out["signups_by_day_30d"] = dict(sorted(by_day.items()))
    return out


def _database():
    started = time.time()
    per_table, total = {}, 0
    for name in _table_names():
        t = _table(name)
        try:
            n = len(t.search())
        except Exception as e:
            per_table[name] = {"rows": None, "error": type(e).__name__}
            continue
        per_table[name] = {"rows": n, "columns": len(_columns(t))}
        total += n
    return {"tables": len(per_table), "total_rows": total, "per_table": per_table,
            "count_ms": int((time.time() - started) * 1000)}


def _errors(now, limit):
    t = _table("error_log")
    if t is None:
        return {"available": False, "note": "No error_log table yet: accept the schema change in the Anvil editor."}
    rows = list(t.search(tables.order_by("when", ascending=False)))
    stamps = [(r, _aware(r["when"])) for r in rows if isinstance(r["when"], dt.datetime)]
    last24 = [r for r, s in stamps if now - s <= dt.timedelta(days=1)]
    last7 = [r for r, s in stamps if now - s <= dt.timedelta(days=7)]
    top = collections.Counter((r["kind"] or "Error", _clip(r["message"], 120)) for r in last7)
    sessions_7d = {r["session"] for r in last7 if r["session"]}
    users_7d = {r["user"].get_id() for r in last7 if r["user"] is not None}
    recent = []
    for r in rows[:limit]:
        u = r["user"]
        recent.append({"when": _iso(r["when"]), "source": r["source"], "kind": r["kind"], "message": r["message"],
                       "page": r["page"], "session": r["session"],
                       "user": (u["email"] if u is not None else None), "traceback": r["traceback"]})
    return {"available": True, "stored": len(rows), "last_24h": len(last24), "last_7d": len(last7),
            "sessions_with_errors_7d": len(sessions_7d), "users_with_errors_7d": len(users_7d),
            "top_7d": [{"kind": k, "message": m, "count": n} for (k, m), n in top.most_common(10)],
            "recent": recent}


def _background_tasks(now):
    try:
        tasks: typing.List[typing.Any] = list(typing.cast(typing.Any, anvil.server.list_background_tasks()))
    except Exception as e:
        return {"available": False, "note": type(e).__name__}
    statuses, failed = collections.Counter(), []
    for task in tasks[:500]:
        try:
            started = _aware(task.get_start_time())
            if started and now - started > dt.timedelta(days=7):
                continue
            status = "running" if task.is_running() else (task.get_termination_status() or "unknown")
            statuses[status] += 1
            if status in ("failed", "killed", "missing") and len(failed) < 20:
                err = None
                try:
                    err = _clip(task.get_error(), 300)
                except Exception:
                    pass
                failed.append({"task": task.get_task_name(), "status": status, "started": _iso(started), "error": err})
        except Exception:
            statuses["unreadable"] += 1
    return {"available": True, "last_7d": dict(statuses), "failed": failed}


def _feedback():
    t = _table("feedback")
    if t is None:
        return None
    cols = _columns(t)
    out = {"total": len(t.search())}
    if "status" in cols:
        out["by_status"] = dict(collections.Counter(r["status"] or "new" for r in t.search()))
    return out


def _app_info(now):
    info = {"report_version": VERSION, "generated": _iso(now), "python": sys.version.split()[0],
            "admin_emails_secret": "set" if AdminAccess.admin_emails() else "missing"}
    try:
        import anvil
        app = anvil.app  # an object on the Anvil server, not a module
        info["app_id"] = getattr(app, "id", None)
        info["branch"] = getattr(app, "branch", None)
        env = getattr(app, "environment", None)
        info["environment"] = getattr(env, "name", None) if env is not None else None
    except Exception:
        pass
    try:
        info["origin"] = anvil.server.get_app_origin()
    except Exception:
        pass
    return info


def build_report(error_limit=20):
    now = _now()
    started = time.time()
    report = {"app": _app_info(now)}
    for key, fn in (("users", lambda: _users(now)), ("database", _database),
                    ("errors", lambda: _errors(now, error_limit)), ("background_tasks", lambda: _background_tasks(now)),
                    ("feedback", _feedback)):
        try:
            report[key] = fn()
        except Exception as e:  # one broken section never hides the rest
            report[key] = {"available": False, "error": "%s: %s" % (type(e).__name__, _clip(e, 200))}
    report["app"]["report_ms"] = int((time.time() - started) * 1000)
    return report


# ------------------------------------------------------------------------------------------------ callables

@anvil.server.callable(require_user=True)
def admin_status_report(error_limit=20):
    _require_admin()
    try:
        error_limit = max(0, min(200, int(error_limit)))
    except (TypeError, ValueError):
        error_limit = 20
    return build_report(error_limit)


@anvil.server.http_endpoint("/admin/status", authenticate_users=True)
def admin_status_endpoint(errors="20", **kw):
    """Signed-in admin (same browser) or HTTP Basic auth with an admin's email + password. Everyone else: 403."""
    user = anvil.users.get_user()
    if not _admin(user):
        return anvil.server.HttpResponse(403, "Admins only.")
    try:
        limit = max(0, min(200, int(errors)))
    except (TypeError, ValueError):
        limit = 20
    resp = anvil.server.HttpResponse(200, json.dumps(build_report(limit), indent=2, default=str))
    resp.headers["Content-Type"] = "application/json"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@anvil.server.callable
def log_client_error(kind=None, message=None, traceback=None, page=None):
    """The browser reports an uncaught error (session_guard.py). Anyone may call it, so it is capped and trimmed."""
    t = _table("error_log")
    if t is None:
        return False
    session = typing.cast(dict, anvil.server.session)
    stamp = _now()
    recent = [s for s in (session.get("error_reports") or []) if (stamp - dt.datetime.fromisoformat(s)).total_seconds() < 3600]
    if len(recent) >= PER_SESSION_LIMIT:
        return False
    session["error_reports"] = recent + [stamp.isoformat()]
    try:
        user = anvil.users.get_user()
    except Exception:
        user = None
    t.add_row(when=stamp, source="browser", kind=_clip(kind, 80) or "Error", message=_clip(message, 1000),
              traceback=_clip(traceback, 4000), page=_clip(page, 300), session=_session_tag(), user=user)
    if random.random() < 0.05:
        _prune(t)
    return True


def log_server_error(where, exc):
    """For server code that catches an error but still wants it in the report: AppStatus.log_server_error("x", e)."""
    t = _table("error_log")
    if t is None:
        return
    import traceback as tb
    try:
        user = anvil.users.get_user()
    except Exception:
        user = None
    try:
        t.add_row(when=_now(), source="server", kind=type(exc).__name__, message=_clip(exc, 1000),
                  traceback=_clip("".join(tb.format_exception(type(exc), exc, exc.__traceback__)), 4000),
                  page=_clip(where, 300), session=_session_tag(), user=user)
    except Exception:
        pass


def _prune(t):
    rows = list(t.search(tables.order_by("when", ascending=False)))
    for r in rows[KEEP_ERRORS:]:
        r.delete()
