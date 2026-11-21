"""What the owner's console pages call. Every function is for admins only (the console is private)."""
import datetime as dt
import random
import secrets

import anvil
import anvil.server
from anvil.tables import app_tables
import anvil.tables as tables
import anvil.tables.query as q

from . import common as C
from . import DemoData, Diagnose, Health, Queue, Styles, Worker


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
            "config": Queue.config(), "problems": Diagnose.problems(7)}


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


# ------------------------------------------------------------------------------------------- problem doctor
@anvil.server.callable(require_user=True)
def console_retry_failed(cause=""):
    """'Try them all again': failed jobs of the last 7 days (all, or those with one cause) go back in the queue."""
    _admin()
    cause = C.text(cause, 30)
    if cause and cause not in Diagnose.keys():
        return C.fail("Unknown cause.")
    since = C.now() - dt.timedelta(days=7)
    n = 0
    for j in app_tables.jobs.search(status="failed", finished=q.greater_than(since)):
        if j["is_demo"]:
            continue
        if cause and (Diagnose.explain(j["error"] or "-") or {}).get("key") != cause:
            continue
        if Queue.retry(j):
            n += 1
        if n >= 200:
            break
    if n:
        Worker.kick("retry")
    return C.ok(count=n)


@anvil.server.callable(require_user=True)
def console_unstick(job_id=None):
    """'Put it back in the queue' for a job the PC looks stuck on."""
    _admin()
    r = Worker.unstick()
    if not r["moved"]:
        return C.fail("Nothing is on the PC right now.")
    return C.ok(moved=r["moved"], pc=pc_status())


@anvil.server.callable(require_user=True)
def console_health(tz_minutes=0):
    _admin()
    d = Health.report(tz_minutes)
    d["pc"] = pc_status()
    return d


# ------------------------------------------------------------------------------------------- contact sheets + make again
def _new_seed():
    return random.randint(1, 2 ** 31 - 1)


def _sheet_jobs(sheet_id):
    if not isinstance(sheet_id, str) or not sheet_id.startswith("sh_"):
        return []
    rows = [j for j in app_tables.jobs.search(tables.order_by("created", ascending=False), origin="console")
            if (j["options"] or {}).get("sheet") == sheet_id]
    return sorted(rows, key=lambda j: int((j["options"] or {}).get("frame") or 0))


def _make_sheet(data, name, style_keys, prompt, fidelity, megapixels, fmt, size, seed):
    sheet_id = "sh_" + secrets.token_hex(6)
    seed = seed if seed not in (None, "") else _new_seed()
    made = []
    for i, key in enumerate(style_keys):
        st, options, _, _ = Queue.clean_options(style=key, prompt=prompt, fidelity=fidelity, megapixels=megapixels,
                                                seed=seed, fmt=fmt, size=size)
        options.update(sheet=sheet_id, frame=i + 1)
        made.append(Queue.create(None, "console", data, name, st, options))
    Worker.kick("queued")
    return sheet_id, made


@anvil.server.callable(require_user=True)
def console_submit_sheet(picture, styles, prompt="", fidelity="balanced", megapixels=1.0, fmt="png", size="model", seed=None):
    """A contact sheet: the same picture in several styles with the same seed, so only the style changes."""
    _admin()
    if picture is None or not hasattr(picture, "get_bytes"):
        return C.fail("Choose a picture first.")
    keys = []
    for k in (styles or []):
        if isinstance(k, str) and k not in keys:
            keys.append(k)
    if len(keys) < 2:
        return C.fail("Pick at least two styles for a contact sheet.")
    if len(keys) > 10:
        return C.fail("A contact sheet holds up to 10 styles.")
    try:
        sheet_id, _ = _make_sheet(picture.get_bytes(), getattr(picture, "name", None) or "picture", keys,
                                  prompt, fidelity, megapixels, fmt, size, seed)
    except Queue.Refused as r:
        return C.fail(r.message)
    return C.ok(sheet_id=sheet_id)


@anvil.server.callable(require_user=True)
def console_sheet(sheet_id):
    _admin()
    rows = _sheet_jobs(sheet_id)
    if not rows:
        return C.fail("That contact sheet isn't here any more (finished jobs are deleted after %d days)." % Queue.config()["keep_days"])
    snap = Queue.snapshot()
    jobs = [Queue.console_dict(j, snap) for j in rows]
    first = jobs[0]
    return C.ok(sheet_id=sheet_id, jobs=jobs, source_url=first["source_url"], source_name=first["source_name"],
                seed=(rows[0]["options"] or {}).get("seed"), fidelity=first["fidelity"], megapixels=first["megapixels"],
                prompt=first["prompt"], created=first["created"])


@anvil.server.callable(require_user=True)
def console_sheet_again(sheet_id):
    """The whole sheet again with a new seed (same picture, styles and options)."""
    _admin()
    rows = _sheet_jobs(sheet_id)
    if not rows:
        return C.fail("That contact sheet isn't here any more.")
    j = rows[0]
    o = j["options"] or {}
    try:
        new_id, _ = _make_sheet(j["source"].get_bytes(), j["source_name"] or "picture", [r["style"] for r in rows],
                                o.get("extra") or "", o.get("fidelity"), o.get("megapixels"), o.get("format"), o.get("size"), None)
    except Queue.Refused as r:
        return C.fail(r.message)
    return C.ok(sheet_id=new_id)


@anvil.server.callable(require_user=True)
def console_again(job_id):
    """'Make again with a new seed': a new console job with the same picture, style and options."""
    _admin()
    j = Queue.find(job_id)
    if j is None:
        return C.fail("That job doesn't exist any more.")
    if j["is_demo"]:
        return C.fail("Demo jobs are examples; they can't be sent to the PC.")
    o = j["options"] or {}
    try:
        st, options, _, _ = Queue.clean_options(style=j["style"], prompt=o.get("extra") or "", fidelity=o.get("fidelity"),
                                                megapixels=o.get("megapixels"), seed=_new_seed(), fmt=o.get("format"),
                                                size=o.get("size"))
        new = Queue.create(None, "console", j["source"].get_bytes(), j["source_name"] or "picture", st, options)
    except Queue.Refused as r:
        return C.fail(r.message)
    Worker.kick("queued")
    return C.ok(job=Queue.console_dict(new))
