"""Talking to the PC over Anvil Uplink, one job at a time.

The PC runs worker/enhancer_worker.py, which connects with the app's SERVER Uplink key and registers two functions:
    imageenhancer_run(job, picture) -> {"image": Media, "seed", "seconds", "model", "backend", "width", "height"}
    imageenhancer_ping()            -> {"busy", "backend", "model", "gpu", "version"}
and calls these on the app:
    enhancer_worker_hello(info)     when it connects and every 5 minutes (heartbeat): "I'm here"
    enhancer_worker_bye()           when it shuts down cleanly

The dispatcher (background task `enhancer_dispatch`) takes the next job and asks the PC to paint it. If the PC
answers, the picture is saved and the next job follows. If the PC isn't there (switched off, worker stopped), the job
goes back to the front of the queue and the dispatcher asks again in 15 minutes (config.retry_minutes), or at once
when the PC says hello. If the PC answers with an error, that job waits 15 minutes and is tried again, up to
config.max_attempts times, then it is marked failed. A scheduled task (`enhancer_tick`, every 15 minutes) restarts
the dispatcher if it ever stopped, puts interrupted jobs back, and deletes old finished jobs.
Only one dispatcher runs: it holds a lease in app_settings["dispatch"] and renews it while it works.
"""
import datetime as dt
import json
import secrets
import time

import anvil
import anvil.http
import anvil.server
from anvil.tables import app_tables
import anvil.tables as tables
import anvil.tables.query as q

from . import common as C
from . import Keys, Pictures, Queue

RUN_FN = "imageenhancer_run"
PING_FN = "imageenhancer_ping"
TASK = "enhancer_dispatch"
JOB_LEASE_MINUTES = 45       # the longest a single job may hold the PC before the lease runs out
WAIT_STEP = 15               # seconds between checks while waiting for the PC
WAIT = [True]                # tests switch the real waiting off
AWAY_ERRORS = {"NoServerFunctionError", "UplinkDisconnectedError", "TimeoutError", "RuntimeUnavailableError",
               "AppOfflineError", "ConnectionError", "ConnectionResetError"}


# ------------------------------------------------------------------------------------------- the lease
def dispatch_state():
    return C.get_setting("dispatch", {}) or {}


def _put(**kw):
    d = dispatch_state()
    d.update(kw)
    C.set_setting("dispatch", d)


@tables.in_transaction
def _claim(owner):
    d = dispatch_state()
    lease = Queue.parse_time(d.get("lease_until"))
    if d.get("owner") and d.get("owner") != owner and lease and lease > C.now() and _task_alive():
        return False
    d.update(owner=owner, lease_until=C.iso(C.now() + dt.timedelta(minutes=2)), state="starting", job_id=None)
    C.set_setting("dispatch", d)
    return True


def _renew(owner, minutes=2, **kw):
    d = dispatch_state()
    if d.get("owner") != owner:
        return False
    d.update(lease_until=C.iso(C.now() + dt.timedelta(minutes=minutes)), beat=C.iso(C.now()), **kw)
    C.set_setting("dispatch", d)
    return True


def _release(owner):
    d = dispatch_state()
    if d.get("owner") == owner:
        d.update(owner=None, lease_until=None, state="idle", job_id=None, until=None)
        C.set_setting("dispatch", d)


def _task_alive():
    """True unless Anvil can tell us no OTHER dispatcher task is running (then a lease left by a killed task is stale)."""
    try:
        tasks = anvil.server.list_background_tasks()
        mine = getattr(anvil.server.context, "background_task_id", None)
    except Exception:
        return True
    return any(t.get_task_name() == TASK and t.is_running() and t.get_id() != mine for t in tasks)


def running():
    d = dispatch_state()
    lease = Queue.parse_time(d.get("lease_until"))
    return bool(d.get("owner") and lease and lease > C.now() and _task_alive())


def kick(reason="queued"):
    """Start the dispatcher unless one is already running. Safe to call often."""
    if running():
        return False
    try:
        anvil.server.launch_background_task(TASK, reason)
    except Exception as e:  # e.g. background tasks unavailable: the scheduled tick tries again
        Queue.event("error", "Couldn't start the dispatcher: %s" % _short(e))
        return False
    return True


# ------------------------------------------------------------------------------------------- the dispatcher
def _short(e):
    s = str(e) or type(e).__name__
    return C.text(s.splitlines()[-1] if s else type(e).__name__, 280)


def _away(e):
    name = type(e).__name__
    return name in AWAY_ERRORS or "not connected" in str(e).lower() or "no server function matching" in str(e).lower()


def recover(include_live=False):
    """Jobs left 'working' by a dispatcher that died go back to the queue (or fail after max_attempts)."""
    if running() and not include_live:
        return 0
    n = 0
    cfg = Queue.config()
    for j in app_tables.jobs.search(status="working"):
        if int(j["attempts"] or 0) >= int(cfg["max_attempts"]):
            j.update(status="failed", finished=C.now(), error="Interrupted while the PC was working on it, too many times.")
            notify(j)
        else:
            j.update(status="queued", started=None)
        n += 1
    return n


def _wait_until(due, owner):
    """Sleep until `due`, the PC saying hello, or a change of plan (paused, lease lost). Returns False to stop."""
    if not WAIT[0]:
        return False
    start = C.now()
    while True:
        if not _renew(owner, 2, state="waiting", until=C.iso(due), job_id=None):
            return False
        if Queue.config()["paused"]:
            return False
        wake = Queue.parse_time(C.get_setting("pc_wake"))
        if wake and wake > start:
            return True
        left = (due - C.now()).total_seconds()
        if left <= 0:
            return True
        time.sleep(min(WAIT_STEP, max(1.0, left)))


@anvil.server.background_task
def enhancer_dispatch(reason="queued"):
    owner = secrets.token_hex(8)
    if not _claim(owner):
        return "another dispatcher is running"
    try:
        recover(include_live=True)
        while True:
            if not _renew(owner, 2):
                return "lost the lease"
            j = Queue.next_ready()
            if j is None:
                due = Queue.next_due_time()
                if due is None or Queue.config()["paused"]:
                    return "idle"
                if not _wait_until(due, owner):
                    return "stopped waiting"
                C.set_setting("pc_retry", {})  # time is up (or the PC said hello): ask again
                continue
            run_job(j, owner)
    finally:
        _release(owner)


def payload(j):
    o = j["options"] or {}
    return {"job_id": j["job_id"], "style": j["style"], "instruction": o.get("instruction") or "",
            "megapixels": o.get("megapixels", 1.0), "seed": o.get("seed"), "format": o.get("format", "png"),
            "size": o.get("size", "model"), "width": j["width"], "height": j["height"],
            "source_name": j["source_name"] or "picture.png", "attempt": int(j["attempts"] or 0)}


def run_job(j, owner=None):
    cfg = Queue.config()
    j.update(status="working", started=C.now(), attempts=int(j["attempts"] or 0) + 1, next_try=None)
    if owner:
        _renew(owner, JOB_LEASE_MINUTES, state="working", job_id=j["job_id"], until=None)
    t0 = time.time()
    try:
        out = anvil.server.call(RUN_FN, payload(j), j["source"])
    except Exception as e:
        if not app_tables.jobs.has_row(j):
            return "gone"
        if _away(e):
            j.update(status="queued", started=None, attempts=max(0, int(j["attempts"] or 1) - 1))
            at = C.now() + dt.timedelta(minutes=int(cfg["retry_minutes"]))
            C.set_setting("pc_retry", {"at": C.iso(at), "reason": _short(e)})
            Queue.event("pc_away", "The PC didn't answer. Asking again in %d minutes." % int(cfg["retry_minutes"]), j["job_id"])
            return "away"
        return _failed_attempt(j, "The PC couldn't make this picture: %s" % _short(e), cfg)
    seconds = time.time() - t0
    if not app_tables.jobs.has_row(j):
        return "gone"
    try:
        img = out["image"] if isinstance(out, dict) else None
        data = img.get_bytes() if img is not None else b""
    except Exception as e:
        return _failed_attempt(j, "The PC's answer couldn't be read: %s" % _short(e), cfg)
    ctype = Pictures.sniff(data)
    if ctype is None:
        return _failed_attempt(j, "The PC answered without a PNG, JPEG or WebP picture.", cfg)
    w, h = Pictures.size(data, ctype)
    info = {k: out.get(k) for k in ("seed", "model", "backend", "steps", "gpu") if out.get(k) is not None}
    info.update(width=w, height=h, pc_seconds=round(float(out.get("seconds") or 0), 1))
    stem = (j["source_name"] or "picture").rsplit(".", 1)[0]
    j.update(status="done", finished=C.now(), seconds=round(seconds, 1), worker_info=info, error=None,
             result=anvil.BlobMedia(ctype, data, name="%s-%s.%s" % (stem, j["style"], Pictures.TYPES[ctype])),
             result_key=secrets.token_urlsafe(24).replace("-", "x").replace("_", "y"))
    _seen(info)
    if Queue.pc_retry_at():
        C.set_setting("pc_retry", {})
    Queue.event("done", "Finished %s in %d s" % (j["job_id"], round(seconds)), j["job_id"])
    notify(j)
    return "done"


def _failed_attempt(j, message, cfg):
    _seen({})
    if int(j["attempts"] or 0) >= int(cfg["max_attempts"]):
        j.update(status="failed", finished=C.now(), error=message)
        Queue.event("failed", "Gave up on %s after %d tries" % (j["job_id"], int(j["attempts"] or 0)), j["job_id"])
        notify(j)
        return "failed"
    at = C.now() + dt.timedelta(minutes=int(cfg["retry_minutes"]))
    j.update(status="queued", started=None, next_try=at, error=message)
    Queue.event("retry", "%s will be tried again in %d minutes" % (j["job_id"], int(cfg["retry_minutes"])), j["job_id"])
    return "retry"


def _seen(info=None):
    old = Queue.pc_seen()
    keep = dict(old.get("info") or {})
    for k in ("model", "backend", "gpu"):
        if info and info.get(k):
            keep[k] = info[k]
    C.set_setting("pc_seen", {"last_seen": C.iso(C.now()), "info": keep})


# ------------------------------------------------------------------------------------------- webhooks
def notify(j):
    """POST the finished job to the app's callback_url, signed with the key's webhook secret."""
    url = j["callback_url"]
    if not url:
        return None
    client = j["client"]
    body = json.dumps({"event": "job." + j["status"], "job": Queue.job_dict(j)}, ensure_ascii=False)
    headers = {"Content-Type": "application/json", "User-Agent": "ImageEnhancer/1.0",
               "X-Enhancer-Event": "job." + j["status"], "X-Enhancer-Job": j["job_id"],
               "X-Enhancer-Signature": Keys.sign(client["webhook_secret"] if client is not None else "", body.encode("utf-8"))}
    try:
        anvil.http.request(url, method="POST", data=body, headers=headers, timeout=10)
        status = "delivered " + C.iso(C.now())
    except anvil.http.HttpError as e:
        status = "failed: the app answered HTTP %s" % getattr(e, "status", "?")
    except Exception as e:
        status = "failed: " + _short(e)
    j["callback_status"] = C.text(status, 200)
    return status


# ------------------------------------------------------------------------------------------- the scheduled tick
@anvil.server.background_task
def enhancer_tick():
    """Every 15 minutes (anvil.yaml scheduled_tasks): restart the dispatcher if needed, tidy up."""
    recover()
    Queue.purge_old()
    Queue.prune_events()
    if Queue.ordered_waiting()[1] and not Queue.config()["paused"]:
        kick("tick")
    return "ok"


# ------------------------------------------------------------------------------------------- called by the PC
def _require_pc():
    """Only the PC (server Uplink key = trusted code) may call these, never a browser."""
    caller = getattr(anvil.server.context, "remote_caller", None)
    if caller is None or not getattr(caller, "is_trusted", False):
        raise anvil.server.PermissionDenied("Only the Image Enhancer worker (server Uplink key) can call this.")


def _clean_info(info):
    info = info if isinstance(info, dict) else {}
    return {k: C.text(info.get(k), 120) for k in ("backend", "model", "gpu", "version", "host") if info.get(k)}


@anvil.server.callable
def enhancer_worker_hello(info=None):
    _require_pc()
    was_away = not Queue.pc_online()
    C.set_setting("pc_seen", {"last_seen": C.iso(C.now()), "info": _clean_info(info)})
    C.set_setting("pc_wake", C.iso(C.now()))
    if Queue.pc_retry_at():
        C.set_setting("pc_retry", {})
    if was_away:
        Queue.event("pc_back", "The PC connected (%s)" % (_clean_info(info).get("backend") or "worker"))
    waiting = len(Queue.ordered_waiting()[1])
    if waiting and not Queue.config()["paused"]:
        kick("hello")
    return {"ok": True, "waiting": waiting, "retry_minutes": int(Queue.config()["retry_minutes"])}


@anvil.server.callable
def enhancer_worker_bye():
    _require_pc()
    seen = Queue.pc_seen()
    seen["last_seen"] = C.iso(C.now() - dt.timedelta(minutes=11))
    C.set_setting("pc_seen", seen)
    Queue.event("pc_away", "The PC disconnected")
    return {"ok": True}


def ping():
    """Ask the PC directly (the console's "Check the PC" button)."""
    try:
        info = anvil.server.call(PING_FN)
    except Exception as e:
        return {"online": False, "error": "The PC isn't connected." if _away(e) else _short(e)}
    info = info if isinstance(info, dict) else {}
    _seen(_clean_info(info))
    return {"online": True, "busy": bool(info.get("busy")), "info": _clean_info(info)}
