"""What the owner's console pages call. Every function is for admins only (the console is private)."""
import anvil
import anvil.server
from anvil.tables import app_tables
import anvil.tables as tables
import anvil.tables.query as q

from . import common as C
from . import DemoData, Queue, Styles, Worker


def _admin():
    C.require_admin()
    Styles.ensure()


def pc_status(snap=None):
    snap = snap or Queue.snapshot()
    seen = Queue.pc_seen()
    d = Worker.dispatch_state()
    retry = snap["retry_at"]
    if snap["paused"]:
        state = "paused"
    elif d.get("state") == "working" and Worker.running():
        state = "working"
    elif retry:
        state = "away"
    elif snap["online"]:
        state = "ready"
    else:
        state = "offline"
    return {"state": state, "last_seen": seen.get("last_seen"), "info": seen.get("info") or {},
            "retry_at": C.iso(retry) if retry else None, "retry_reason": (C.get_setting("pc_retry", {}) or {}).get("reason"),
            "dispatcher": d.get("state") or "idle", "dispatcher_running": Worker.running(),
            "job_id": d.get("job_id"), "paused": snap["paused"]}


@anvil.server.callable(require_user=True)
def console_overview():
    _admin()
    DemoData.ensure_loaded()
    snap = Queue.snapshot()
    working, queued = Queue.ordered_waiting()
    recent = [j for j in app_tables.jobs.search(tables.order_by("finished", ascending=False),
                                                status=q.any_of("done", "failed", "cancelled"))][:12]
    events = list(app_tables.events.search(tables.order_by("time", ascending=False)))[:14]
    return {"pc": pc_status(snap), "queue": Queue.queue_info(snap), "counts": Queue.counts(),
            "waiting": [Queue.console_dict(j, snap) for j in (working + queued)[:60]],
            "more_waiting": max(0, len(working) + len(queued) - 60),
            "recent": [Queue.console_dict(j, snap) for j in recent],
            "events": [{"time": C.iso(e["time"]), "kind": e["kind"], "text": e["text"], "job_id": e["job_id"]} for e in events],
            "config": Queue.config()}


@anvil.server.callable(require_user=True)
def console_history(status="all", query="", limit=60):
    _admin()
    rows = app_tables.jobs.search(tables.order_by("created", ascending=False))
    status = status if status in Queue.STATUSES else "all"
    query = C.text(query, 60).lower()
    out = []
    snap = Queue.snapshot()
    for j in rows:
        if status != "all" and j["status"] != status:
            continue
        if query:
            hay = " ".join([j["job_id"], j["style"], j["client"]["name"] if j["client"] is not None else "",
                            j["client_ref"] or "", j["source_name"] or ""]).lower()
            if query not in hay:
                continue
        out.append(Queue.console_dict(j, snap))
        if len(out) >= max(1, min(200, int(limit or 60))):
            break
    return {"jobs": out}


@anvil.server.callable(require_user=True)
def console_job(job_id):
    _admin()
    j = Queue.find(job_id)
    if j is None:
        return C.fail("That job doesn't exist any more (finished jobs are deleted after %d days)." % Queue.config()["keep_days"])
    return C.ok(job=Queue.console_dict(j))


@anvil.server.callable(require_user=True)
def console_styles():
    """The enabled styles, for the test bench's picker."""
    _admin()
    return {"styles": [Styles.public(r) for r in Styles.rows(True)], "fidelity": list(Styles.FIDELITY)}


@anvil.server.callable(require_user=True)
def console_submit(picture, style, prompt="", fidelity="balanced", megapixels=1.0, fmt="png", size="model", seed=None):
    """The test bench: send a picture from the browser, exactly like an app would (but without a key)."""
    _admin()
    if picture is None or not hasattr(picture, "get_bytes"):
        return C.fail("Choose a picture first.")
    try:
        st, options, _, _ = Queue.clean_options(style=style, prompt=prompt, fidelity=fidelity, megapixels=megapixels,
                                                seed=seed, fmt=fmt, size=size)
        j = Queue.create(None, "console", picture.get_bytes(), getattr(picture, "name", None) or "picture", st, options)
    except Queue.Refused as r:
        return C.fail(r.message)
    Worker.kick("queued")
    return C.ok(job=Queue.console_dict(j))


@anvil.server.callable(require_user=True)
def console_cancel(job_id):
    _admin()
    j = Queue.find(job_id)
    if j is None:
        return C.fail("That job doesn't exist any more.")
    if not Queue.cancel(j):
        return C.fail("Only a waiting job can be cancelled; this one is %s." % j["status"])
    return C.ok(job=Queue.console_dict(j))


@anvil.server.callable(require_user=True)
def console_retry(job_id):
    _admin()
    j = Queue.find(job_id)
    if j is None:
        return C.fail("That job doesn't exist any more.")
    if j["is_demo"]:
        return C.fail("Demo jobs are examples; they can't be sent to the PC.")
    if not Queue.retry(j):
        return C.fail("Only a failed or cancelled job can be tried again.")
    Worker.kick("retry")
    return C.ok(job=Queue.console_dict(j))


@anvil.server.callable(require_user=True)
def console_next(job_id):
    """'Do this next': the job jumps to the front of the queue."""
    _admin()
    j = Queue.find(job_id)
    if j is None or j["status"] != "queued":
        return C.fail("Only a waiting job can be moved to the front.")
    top = max([int(x["priority"] or 0) for x in app_tables.jobs.search(status="queued")] + [0])
    j["priority"] = top + 1
    Queue.event("queued", "Moved %s to the front" % j["job_id"], j["job_id"])
    return C.ok()


@anvil.server.callable(require_user=True)
def console_delete(job_id):
    _admin()
    j = Queue.find(job_id)
    if j is None:
        return C.ok()
    if j["status"] == "working":
        return C.fail("The PC is working on this one right now. Wait for it to finish, then delete it.")
    j.delete()
    return C.ok()


@anvil.server.callable(require_user=True)
def console_kick():
    """'Ask the PC now': forget the 15-minute wait and try straight away."""
    _admin()
    C.set_setting("pc_retry", {})
    C.set_setting("pc_wake", C.iso(C.now()))
    started = Worker.kick("console") if Queue.ordered_waiting()[1] else False
    return C.ok(started=started, pc=pc_status())


@anvil.server.callable(require_user=True)
def console_ping():
    _admin()
    r = Worker.ping()
    return C.ok(result=r, pc=pc_status())


@anvil.server.callable(require_user=True)
def console_pause(flag):
    _admin()
    cfg = Queue.config()
    cfg["paused"] = bool(flag)
    C.set_setting("config", cfg)
    Queue.event("paused" if flag else "resumed", "Queue paused: nothing is sent to the PC" if flag else "Queue resumed")
    if not flag:
        Worker.kick("resumed")
    return C.ok(pc=pc_status())


@anvil.server.callable(require_user=True)
def console_save_config(retry_minutes, max_attempts, keep_days):
    _admin()
    try:
        r, m, k = int(retry_minutes), int(max_attempts), int(keep_days)
    except (TypeError, ValueError):
        return C.fail("Use whole numbers.")
    if not 1 <= r <= 240:
        return C.fail("Ask the PC again every 1 to 240 minutes.")
    if not 1 <= m <= 10:
        return C.fail("Try a picture 1 to 10 times.")
    if not 1 <= k <= 365:
        return C.fail("Keep finished jobs 1 to 365 days.")
    cfg = Queue.config()
    cfg.update(retry_minutes=r, max_attempts=m, keep_days=k)
    C.set_setting("config", cfg)
    return C.ok(config=cfg)


@anvil.server.callable(require_user=True)
def console_setup():
    """Facts for the Connect page: the API base address and the PC's state."""
    _admin()
    return {"api_base": Queue.api_origin() + "/v1", "pc": pc_status(), "config": Queue.config(),
            "styles": [Styles.public(r) for r in Styles.rows(True)]}
