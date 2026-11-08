"""Feedback: anyone (even signed out) can report a bug or an idea; admins read them in Admin -> Feedback."""
import anvil.server
from anvil.tables import app_tables
import anvil.tables as tables

from . import common as C

KINDS = {"bug": "Bug", "idea": "Idea", "question": "Question", "other": "Other"}
STATUSES = ["new", "read", "done"]
LIMIT_PER_HOUR = 5


def _context(ctx):
    """Keep only short, known details the page sends (screen, page, browser)."""
    if not isinstance(ctx, dict):
        return {}
    out = {}
    for k in ("page", "screen", "browser", "theme", "app_version"):
        if k in ctx:
            out[k] = C.text(ctx[k], 300)
    return out


@anvil.server.callable
def submit_feedback(kind, message, email=None, context=None):
    message = C.text(message, 4000, multiline=True)
    if len(message) < 5:
        return C.fail("Please write a little more (at least 5 characters).")
    if C.rate_limited("feedback", LIMIT_PER_HOUR, 3600):
        return C.fail("Thanks! You've sent a lot of messages this hour. Please try again a bit later.")
    user = C.me()
    email = C.text(email, 120).replace(" ", "") or (user["email"] if user else "")
    app_tables.feedback.add_row(user=user, name=C.name_of(user) if user else "Guest", email=email or None,
                                kind=kind if kind in KINDS else "other", message=message,
                                context=_context(context), status="new", note="", created=C.now())
    return C.ok()


def _row(r):
    return {"id": r.get_id(), "kind": r["kind"], "kind_label": KINDS.get(r["kind"], "Other"), "message": r["message"],
            "name": r["name"], "email": r["email"], "status": r["status"], "note": r["note"] or "",
            "context": r["context"] or {}, "created": C.iso(r["created"]), "signed_in": r["user"] is not None}


@anvil.server.callable(require_user=True)
def list_feedback(status=None):
    C.require_admin()
    rows = app_tables.feedback.search(tables.order_by("created", ascending=False))
    counts = {s: 0 for s in STATUSES}
    for r in rows:
        counts[r["status"] if r["status"] in counts else "new"] += 1
    items = [_row(r) for r in rows if not status or r["status"] == status]
    return {"items": items, "counts": counts}


@anvil.server.callable(require_user=True)
def set_feedback_status(feedback_id, status, note=None):
    C.require_admin()
    row = C.row_by_id(app_tables.feedback, feedback_id)
    if row is None:
        return C.fail("That message no longer exists.")
    if status not in STATUSES:
        return C.fail("Unknown status.")
    row["status"] = status
    if note is not None:
        row["note"] = C.text(note, 2000, multiline=True)
    return C.ok(item=_row(row))


@anvil.server.callable(require_user=True)
def delete_feedback(feedback_id):
    C.require_admin()
    row = C.row_by_id(app_tables.feedback, feedback_id)
    if row is not None:
        row.delete()
    return C.ok()


def new_count():
    return len(app_tables.feedback.search(status="new"))
