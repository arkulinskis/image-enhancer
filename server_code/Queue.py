"""The job queue: one picture in, one restyled picture out, strictly one at a time, oldest first.

    status: queued -> working -> done | failed      (cancelled: by the app or the owner, while still waiting)
    order:  priority (higher first; "Do next" in the console), then created (oldest first)
    eta:    from the average time of recent finished jobs (per style when there are enough), counting the job now
            on the PC, every job ahead, and the PC's next "ask again" time if it was away.

Shared by the HTTP API (Api.py), the console (Console.py) and the dispatcher that talks to the PC (Worker.py).
The PC's state lives in app_settings under separate keys (one writer each, so updates never overwrite each other):
    pc_seen   {last_seen, info}          written when the PC says hello or finishes a job
    pc_retry  {at, reason}               when the dispatcher will ask the PC again (it was away)
    pc_wake   iso time                   the PC said hello: the dispatcher stops waiting and asks at once
    dispatch  {state, job_id, lease_until, beat}   what the dispatcher is doing (and a lease, in case it died)
    config    {retry_minutes, max_attempts, keep_days, paused}
"""
import datetime as dt
import secrets

import anvil
import anvil.server
from anvil.tables import app_tables
import anvil.tables as tables
import anvil.tables.query as q

from . import common as C
from . import Pictures, Styles

STATUSES = ("queued", "working", "done", "failed", "cancelled")
OPEN = ("queued", "working")
DEFAULT_SECONDS = 90         # until the first jobs finish: model load + 4 sampling steps on an 8 GB laptop GPU
OVERHEAD_SECONDS = 4         # hand-over per job (upload to the PC, download of the result)
FORMATS = ("png", "jpeg", "webp")
SIZES = ("model", "source")
MAX_WAITING_PER_CLIENT = 500
MAX_QUEUE = 2000
DEFAULT_CONFIG = {"retry_minutes": 15, "max_attempts": 3, "keep_days": 30, "paused": False}


# ------------------------------------------------------------------------------------------- settings + state
def config():
    c = dict(DEFAULT_CONFIG)
    c.update(C.get_setting("config", {}) or {})
    return c


def parse_time(v):
    if not v:
        return None
    try:
        t = dt.datetime.fromisoformat(v)
        return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def pc_seen():
    return C.get_setting("pc_seen", {}) or {}


def pc_retry_at():
    return parse_time((C.get_setting("pc_retry", {}) or {}).get("at"))


def pc_online():
    """The PC counts as online if it said hello or finished a job in the last 10 minutes (it says hello every 5)."""
    seen = parse_time(pc_seen().get("last_seen"))
    return bool(seen and (C.now() - seen).total_seconds() < 600 and not pc_retry_at())


def event(kind, text, job_id=None, demo=False):
    app_tables.events.add_row(time=C.now(), kind=kind, text=C.text(text, 300), job_id=job_id, is_demo=demo)


def prune_events(keep=400):
    rows = list(app_tables.events.search(tables.order_by("time", ascending=False)))
    for r in rows[keep:]:
        r.delete()


def api_origin():
    try:
        return anvil.server.get_api_origin().rstrip("/")
    except Exception:
        return ""


def file_url(key):
    return "%s/v1/files/%s" % (api_origin(), key) if key else None


# ------------------------------------------------------------------------------------------- timing
def averages():
    """{style: seconds, "_all": seconds} from the last 40 finished jobs."""
    done = [j for j in app_tables.jobs.search(tables.order_by("finished", ascending=False), status="done")
            if not j["is_demo"] and j["seconds"]][:40]
    out: dict = {"_all": (sum(j["seconds"] for j in done) / len(done)) if done else DEFAULT_SECONDS}
    by: dict = {}
    for j in done:
        by.setdefault(j["style"], []).append(j["seconds"])
    for k, v in by.items():
        if len(v) >= 3:
            out[k] = sum(v) / len(v)
    return out


def ordered_waiting():
    rows = [j for j in app_tables.jobs.search(status=q.any_of(*OPEN)) if not j["is_demo"]]
    working = sorted([j for j in rows if j["status"] == "working"], key=lambda j: j["started"] or j["created"])
    queued = sorted([j for j in rows if j["status"] == "queued"],
                    key=lambda j: (-(j["priority"] or 0), j["created"]))
    return working, queued


def snapshot():
    """Positions and finish-time estimates for every open job, plus the estimate for a job sent now."""
    cfg = config()
    avg = averages()
    working, queued = ordered_waiting()
    stamp = C.now()
    retry = pc_retry_at()
    t = stamp
    order: dict = {}
    for j in working:
        took = (stamp - (j["started"] or stamp)).total_seconds()
        left = max(8.0, avg.get(j["style"], avg["_all"]) - took)
        t = stamp + dt.timedelta(seconds=left)
        order[j["job_id"]] = (0, t)
    if retry and retry > t:
        t = retry
    for i, j in enumerate(queued):
        nt = j["next_try"]
        if nt and nt > t:
            t = nt
        t = t + dt.timedelta(seconds=avg.get(j["style"], avg["_all"]) + OVERHEAD_SECONDS)
        order[j["job_id"]] = (i + 1, t)
    eta_new = t + dt.timedelta(seconds=avg["_all"] + OVERHEAD_SECONDS)
    return {"order": order, "working": len(working), "queued": len(queued), "eta_new": eta_new,
            "avg_seconds": round(avg["_all"], 1), "paused": bool(cfg["paused"]), "retry_at": retry,
            "online": pc_online(), "now": stamp}


def _eta(snap, job_id):
    if job_id not in snap["order"]:
        return None, None, None
    pos, at = snap["order"][job_id]
    if snap["paused"]:
        return pos, None, None
    return pos, max(0, int(round((at - snap["now"]).total_seconds()))), C.iso(at)


def queue_info(snap=None):
    snap = snap or snapshot()
    secs = max(0, int(round((snap["eta_new"] - snap["now"]).total_seconds())))
    return {"waiting": snap["queued"], "working": snap["working"], "queue_length": snap["queued"] + snap["working"],
            "pc_online": snap["online"], "paused": snap["paused"],
            "pc_next_try_at": C.iso(snap["retry_at"]) if snap["retry_at"] else None,
            "average_seconds": snap["avg_seconds"],
            "eta_new_job_seconds": None if snap["paused"] else secs,
            "eta_new_job_at": None if snap["paused"] else C.iso(snap["eta_new"])}


# ------------------------------------------------------------------------------------------- job shapes
def job_dict(j, snap=None):
    """What an app gets back from the API (no internal row ids, no other apps' data)."""
    o = j["options"] or {}
    d = {"id": j["job_id"], "status": j["status"], "style": j["style"], "style_label": Styles.label_of(j["style"]),
         "prompt": o.get("extra") or "", "fidelity": o.get("fidelity", "balanced"), "megapixels": o.get("megapixels", 1.0),
         "size": o.get("size", "model"), "format": o.get("format", "png"), "seed": (j["worker_info"] or {}).get("seed", o.get("seed")),
         "ref": j["client_ref"] or None, "source_name": j["source_name"] or None,
         "width": j["width"], "height": j["height"],
         "created": C.iso(j["created"]), "started": C.iso(j["started"]), "finished": C.iso(j["finished"]),
         "attempts": int(j["attempts"] or 0), "error": j["error"] or None,
         "seconds": round(j["seconds"], 1) if j["seconds"] else None,
         "source_url": file_url(j["source_key"]),
         "result_url": file_url(j["result_key"]) if j["status"] == "done" and j["result_key"] else None,
         "result_width": (j["worker_info"] or {}).get("width"), "result_height": (j["worker_info"] or {}).get("height"),
         "callback": {"url": j["callback_url"], "status": j["callback_status"]} if j["callback_url"] else None,
         "position": None, "eta_seconds": None, "eta_at": None, "next_try_at": None}
    if j["status"] in OPEN:
        snap = snap or snapshot()
        d["position"], d["eta_seconds"], d["eta_at"] = _eta(snap, j["job_id"])
        nt = j["next_try"] or (snap["retry_at"] if j["status"] == "queued" else None)
        if nt and nt > snap["now"]:
            d["next_try_at"] = C.iso(nt)
    return d


def console_dict(j, snap=None):
    d = job_dict(j, snap)
    d.update({"row_id": j.get_id(), "app": j["client"]["name"] if j["client"] is not None else (
                  "Console" if j["origin"] == "console" else "Deleted app"),
              "origin": j["origin"] or "api", "priority": int(j["priority"] or 0), "demo": bool(j["is_demo"]),
              "worker": j["worker_info"] or {}, "instruction": (j["options"] or {}).get("instruction", "")})
    return d


def find(job_id, client=None):
    """A job by its public id; with client, only that app's own jobs."""
    if not isinstance(job_id, str) or not job_id.startswith("job_"):
        return None
    j = app_tables.jobs.get(job_id=job_id)
    if j is None or (client is not None and j["client"] != client):
        return None
    return j


# ------------------------------------------------------------------------------------------- creating jobs
class Refused(Exception):
    def __init__(self, status, message):
        Exception.__init__(self, message)
        self.status, self.message = status, message


def _int(v, name, low, high, default):
    if v in (None, ""):
        return default
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise Refused(400, "%s must be a whole number." % name)
    if not low <= n <= high:
        raise Refused(400, "%s must be between %s and %s." % (name, low, high))
    return n


def clean_options(style=None, prompt="", fidelity="balanced", megapixels=None, seed=None, fmt="png", size="model",
                  callback_url=None, ref=None):
    """Checks everything an app may send with a picture. Raises Refused with a message the app's developer can act on."""
    st = Styles.get(style)
    if st is None or not st["enabled"]:
        keys = ", ".join(r["key"] for r in Styles.rows(True))
        raise Refused(400, "Unknown style “%s”. Use one of: %s." % (C.text(style, 40), keys))
    fidelity = (fidelity or "balanced").lower()
    if fidelity not in Styles.FIDELITY:
        raise Refused(400, "fidelity must be loose, balanced or strict.")
    try:
        mp = float(megapixels) if megapixels not in (None, "") else 1.0
    except (TypeError, ValueError):
        raise Refused(400, "megapixels must be a number between 0.25 and 2.")
    if not 0.25 <= mp <= 2.0:
        raise Refused(400, "megapixels must be between 0.25 and 2 (1 is what the model was trained for).")
    fmt = (fmt or "png").lower().replace("jpg", "jpeg")
    if fmt not in FORMATS:
        raise Refused(400, "format must be png, jpeg or webp.")
    size = (size or "model").lower()
    if size not in SIZES:
        raise Refused(400, "size must be “model” (what the model makes, about 1 megapixel) or “source” (the size of your picture).")
    cb = C.text(callback_url, 500) if callback_url else None
    if cb and not cb.startswith("https://"):
        raise Refused(400, "callback_url must start with https://")
    return st, {"fidelity": fidelity, "megapixels": round(mp, 2), "seed": _int(seed, "seed", 0, 2 ** 48, None),
                "format": fmt, "size": size, "extra": C.text(prompt, 600),
                "instruction": Styles.instruction(st, fidelity, prompt)}, cb, C.text(ref, 120) or None


def check_picture(data, name=""):
    if not data:
        raise Refused(400, "No picture came with the request.")
    if len(data) > Pictures.MAX_BYTES:
        raise Refused(413, "The picture is %.1f MB; the limit is 15 MB." % (len(data) / 1048576.0))
    ctype = Pictures.sniff(data)
    if ctype is None:
        if Pictures.looks_like_svg(data):
            raise Refused(415, "SVG files can't be sent as they are: export the vector art as a PNG first (1024 px or more on the long side works best).")
        raise Refused(415, "The picture must be a PNG, JPEG or WebP file.")
    w, h = Pictures.size(data, ctype)
    if w and h and (w > Pictures.MAX_SIDE or h > Pictures.MAX_SIDE):
        raise Refused(413, "The picture is %dx%d; the longest side may be %d px." % (w, h, Pictures.MAX_SIDE))
    if w and h and min(w, h) < 64:
        raise Refused(400, "The picture is only %dx%d; send at least 64 px on each side." % (w, h))
    return ctype, w, h


def _token(n=24):
    return secrets.token_urlsafe(n).replace("-", "x").replace("_", "y")


def create(client, origin, data, name, style, options, callback_url=None, ref=None):
    """Checks the picture and the limits, then adds the job. Returns the row. Raises Refused."""
    ctype, w, h = check_picture(data, name)
    if client is not None:
        hour_ago = C.now() - dt.timedelta(hours=1)
        recent = len([j for j in app_tables.jobs.search(client=client, created=q.greater_than(hour_ago))])
        if recent >= int(client["hourly_limit"] or 60):
            raise Refused(429, "This key may send %d pictures an hour and has reached that. Try again later, or raise its limit in the console." % int(client["hourly_limit"] or 60))
        waiting = len(app_tables.jobs.search(client=client, status=q.any_of(*OPEN)))
        if waiting >= MAX_WAITING_PER_CLIENT:
            raise Refused(429, "This app already has %d pictures waiting. Wait for some to finish." % waiting)
    if len(app_tables.jobs.search(status=q.any_of(*OPEN))) >= MAX_QUEUE:
        raise Refused(503, "The queue is full (%d pictures). Try again later." % MAX_QUEUE)
    ext = Pictures.TYPES[ctype]
    base = C.text(name, 80) or "picture"
    if "." not in base[-6:]:
        base = base + "." + ext
    job_id = "job_" + _token(9)[:12]
    j = app_tables.jobs.add_row(
        job_id=job_id, client=client, origin=origin, style=style["key"], prompt=options.get("extra") or "",
        options=options, source=anvil.BlobMedia(ctype, data, name=base), source_key=_token(), source_name=base,
        width=w, height=h, status="queued", priority=0, created=C.now(), attempts=0, callback_url=callback_url,
        client_ref=ref, is_demo=False)
    if client is not None:
        client["jobs_total"] = int(client["jobs_total"] or 0) + 1
    event("queued", "%s sent a picture for %s" % (client["name"] if client is not None else "Console", style["label"]), job_id)
    return j


# ------------------------------------------------------------------------------------------- changing jobs
def cancel(j):
    if j["status"] == "queued":
        j.update(status="cancelled", finished=C.now(), error="Cancelled before the PC started it.")
        event("cancelled", "Cancelled %s" % j["job_id"], j["job_id"])
        return True
    return False


def retry(j):
    """A failed or cancelled job goes back in the queue, at the end, with its attempts reset."""
    if j["status"] in ("failed", "cancelled"):
        j.update(status="queued", attempts=0, error=None, next_try=None, started=None, finished=None, created=C.now())
        event("queued", "Sent %s back to the queue" % j["job_id"], j["job_id"])
        return True
    return False


def next_ready():
    """The job the dispatcher should send to the PC now, or None (paused, PC away, nothing due)."""
    cfg = config()
    if cfg["paused"]:
        return None
    retry_at = pc_retry_at()
    stamp = C.now()
    if retry_at and retry_at > stamp:
        return None
    working, queued = ordered_waiting()
    if working:
        return None
    for j in queued:
        if j["next_try"] is None or j["next_try"] <= stamp:
            return j
    return None


def next_due_time():
    """When something will next be due (for the dispatcher's wait), or None when nothing is waiting."""
    working, queued = ordered_waiting()
    if not queued:
        return None
    times = [j["next_try"] or C.now() for j in queued]
    t = min(times)
    r = pc_retry_at()
    return max(t, r) if r else t


def purge_old():
    """Finished jobs older than keep_days are deleted (pictures included)."""
    days = int(config()["keep_days"] or 30)
    cutoff = C.now() - dt.timedelta(days=days)
    n = 0
    for j in app_tables.jobs.search(status=q.any_of("done", "failed", "cancelled"),
                                    created=q.less_than(cutoff)):
        if not j["is_demo"]:
            j.delete()
            n += 1
    return n


def counts():
    out = {s: 0 for s in STATUSES}
    for j in app_tables.jobs.search():
        if not j["is_demo"] and j["status"] in out:
            out[j["status"]] += 1
    return out
