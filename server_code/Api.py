"""The HTTP API your other apps call. Base address: https://<this app>/_/api/v1 . Every call except /health needs a key
from the console's Apps & keys page in the header (never in the address):

    Authorization: Bearer ie_...

    GET  /v1/health                    is the service up (no key needed; says nothing private)
    GET  /v1/styles                    the styles you can ask for: [{key, label, description}]
    GET  /v1/queue                     queue length, is the PC online, estimated finish time for a picture sent now
    POST /v1/jobs                      send a picture -> 202 {job}. Three ways to send it:
                                         JSON: {"image": "<base64 or data URL>" | "image_url": "https://...",
                                                "style": "kids_book", "prompt": "extra words", "fidelity": "balanced",
                                                "megapixels": 1, "seed": 42, "format": "png", "size": "model",
                                                "callback_url": "https://your-app/...", "ref": "your own id"}
                                         raw bytes: Content-Type image/png (or jpeg/webp), options in the address
                                                (?style=kids_book&fidelity=strict ...)
                                         multipart/form-data: a file field "image" + the same fields
    GET  /v1/jobs                      your app's jobs ?status=queued|working|done|failed|cancelled|open &limit=20
    GET  /v1/jobs/<id>                 one job: status, position, eta_seconds, eta_at, result_url when done
                                       ?wait=20 holds the answer up to 20 s until the job finishes (fewer polls)
    GET  /v1/jobs/<id>/result          the finished picture itself (image/png, image/jpeg or image/webp)
    POST /v1/jobs/<id>/cancel          cancel a job that hasn't started (DELETE /v1/jobs/<id> does the same)
    GET  /v1/files/<key>               a picture by its unguessable link (result_url / source_url): no key needed,
                                       so you can put it straight into an <img> tag; deleted with the job

Answers are JSON: {"ok": true, ...} or {"ok": false, "error": "what went wrong and what to do"} with a 4xx/5xx code.
When a job finishes and it has a callback_url, the service POSTs {"event": "job.done" | "job.failed", "job": {...}}
there, signed: X-Enhancer-Signature: sha256=<HMAC-SHA256 of the raw body with the key's webhook secret>.
"""
import json
import time

import anvil
import anvil.http
import anvil.server
from anvil.tables import app_tables
import anvil.tables as tables
import anvil.tables.query as q

from . import common as C
from . import Keys, Queue, Styles, Worker

VERSION = "1.0"


def _json(status, data, extra=None):
    headers = {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store",
               "X-Content-Type-Options": "nosniff"}
    headers.update(extra or {})
    return anvil.server.HttpResponse(status, json.dumps(data, ensure_ascii=False), headers=headers)


def _header(name):
    h = getattr(anvil.server.request, "headers", None) or {}
    for k in h:
        if k.lower() == name:
            return h[k] or ""
    return ""


def _method():
    return (getattr(anvil.server.request, "method", None) or "GET").upper()


def _auth(params):
    if any(k in params for k in ("key", "api_key", "token")):
        return None, _json(400, {"ok": False, "error": "Don't put API keys in the address (they end up in logs). Use the header Authorization: Bearer ie_..."})
    auth = _header("authorization")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else _header("x-api-key")
    client, err = Keys.authenticate(token)
    if err:
        return None, _json(err[0], {"ok": False, "error": err[1]})
    return client, None


def _serve(params, fn):
    client, bad = _auth(params)
    if bad is not None:
        return bad
    try:
        return fn(client)
    except Queue.Refused as r:
        return _json(r.status, {"ok": False, "error": r.message})


# ------------------------------------------------------------------------------------------- reading a request
def _body_bytes():
    b = getattr(anvil.server.request, "body", None)
    if b is None:
        return b""
    if hasattr(b, "get_bytes"):
        return b.get_bytes() or b""
    if isinstance(b, str):
        return b.encode("latin-1", "ignore")
    return bytes(b)


def _body_json():
    r = anvil.server.request
    try:
        b = r.body_json
        b = b() if hasattr(b, "__call__") else b
    except Exception:
        raise Queue.Refused(400, "The request body must be JSON (or send the picture as image/png bytes or multipart).")
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise Queue.Refused(400, "The JSON body must be an object, e.g. {\"image\": \"...\", \"style\": \"kids_book\"}.")
    return b


def _fetch(url):
    if not isinstance(url, str) or not url.startswith("https://"):
        raise Queue.Refused(400, "image_url must start with https://")
    try:
        got = anvil.http.request(url, method="GET", timeout=20)
    except anvil.http.HttpError as e:
        raise Queue.Refused(400, "Couldn't download image_url (HTTP %s)." % getattr(e, "status", "?"))
    except Exception:
        raise Queue.Refused(400, "Couldn't download image_url.")
    data = got.get_bytes() if hasattr(got, "get_bytes") else (got.encode("latin-1") if isinstance(got, str) else bytes(got))
    return data, url.rsplit("/", 1)[-1].split("?")[0][:80]


def read_submission(params):
    """(picture bytes, file name, fields dict) from JSON, raw bytes or multipart."""
    ctype = _header("content-type").lower()
    fields = {k: v for k, v in params.items() if not hasattr(v, "get_bytes")}
    files = [v for v in params.values() if hasattr(v, "get_bytes")]
    if files:  # multipart: Anvil hands over the file part as Media
        f = params.get("image") if hasattr(params.get("image"), "get_bytes") else files[0]
        return f.get_bytes(), getattr(f, "name", None) or "picture", fields
    if ctype.startswith("application/json"):
        body = _body_json()
        fields.update({k: v for k, v in body.items() if k not in ("image", "image_url")})
        if body.get("image"):
            data = Queue.Pictures.decode_base64(body["image"])
            if data is None:
                raise Queue.Refused(400, "“image” must be base64 (or a data: URL) of a PNG, JPEG or WebP file.")
            return data, C.text(body.get("filename"), 80) or "picture", fields
        if body.get("image_url"):
            data, name = _fetch(body["image_url"])
            return data, name, fields
        raise Queue.Refused(400, "Send the picture as “image” (base64) or “image_url”.")
    if ctype.startswith("image/") or ctype.startswith("application/octet-stream"):
        # raw bytes: options come only from the address (Anvil may also hand bits of the body over as "fields")
        q = getattr(anvil.server.request, "query_params", None) or {}
        fields = {k: q[k] for k in q if isinstance(q[k], str)}
        return _body_bytes(), C.text(fields.get("filename"), 80) or "picture", fields
    raise Queue.Refused(415, "Send JSON (Content-Type: application/json), the picture's bytes (Content-Type: image/png) or multipart/form-data.")


def submit(client, params):
    data, name, f = read_submission(params)
    style, options, cb, ref = Queue.clean_options(
        style=f.get("style"), prompt=f.get("prompt") or "", fidelity=f.get("fidelity"), megapixels=f.get("megapixels"),
        seed=f.get("seed"), fmt=f.get("format"), size=f.get("size"), callback_url=f.get("callback_url"), ref=f.get("ref"))
    j = Queue.create(client, "api", data, name, style, options, cb, ref)
    Worker.kick("queued")
    snap = Queue.snapshot()
    return {"job": Queue.job_dict(j, snap), "queue": Queue.queue_info(snap)}


# ------------------------------------------------------------------------------------------- endpoints
@anvil.server.http_endpoint("/v1/health", methods=["GET"])
def api_health(**params):
    return _json(200, {"ok": True, "service": "Image Enhancer", "version": VERSION})


@anvil.server.http_endpoint("/v1/styles", methods=["GET"])
def api_styles(**params):
    def go(client):
        return _json(200, {"ok": True, "styles": [Styles.public(r) for r in Styles.rows(True)],
                           "fidelity": list(Styles.FIDELITY), "formats": list(Queue.FORMATS), "sizes": list(Queue.SIZES)})
    return _serve(params, go)


@anvil.server.http_endpoint("/v1/queue", methods=["GET"])
def api_queue(**params):
    def go(client):
        info = Queue.queue_info()
        info["yours_waiting"] = len(app_tables.jobs.search(client=client, status=q.any_of(*Queue.OPEN)))
        return _json(200, dict(info, ok=True))
    return _serve(params, go)


@anvil.server.http_endpoint("/v1/jobs", methods=["GET", "POST"])
def api_jobs(**params):
    def go(client):
        if _method() == "POST":
            return _json(202, dict(submit(client, params), ok=True))
        status = (params.get("status") or "").lower()
        try:
            limit = max(1, min(100, int(params.get("limit") or 20)))
        except (TypeError, ValueError):
            limit = 20
        rows = app_tables.jobs.search(tables.order_by("created", ascending=False), client=client)
        if status == "open":
            rows = [j for j in rows if j["status"] in Queue.OPEN]
        elif status in Queue.STATUSES:
            rows = [j for j in rows if j["status"] == status]
        elif status:
            raise Queue.Refused(400, "status must be one of: open, %s." % ", ".join(Queue.STATUSES))
        rows = list(rows)[:limit]
        snap = Queue.snapshot()
        return _json(200, {"ok": True, "jobs": [Queue.job_dict(j, snap) for j in rows]})
    return _serve(params, go)


@anvil.server.http_endpoint("/v1/jobs/:job_id", methods=["GET", "DELETE"])
def api_job(job_id, **params):
    def go(client):
        j = Queue.find(job_id, client)
        if j is None:
            return _json(404, {"ok": False, "error": "No job %s for this key." % C.text(job_id, 40)})
        if _method() == "DELETE":
            return _cancel(j)
        try:
            wait = max(0, min(20, int(params.get("wait") or 0)))
        except (TypeError, ValueError):
            wait = 0
        end = time.time() + wait
        while wait and j["status"] in Queue.OPEN and time.time() < end:
            time.sleep(1.5)
            j = Queue.find(job_id, client) or j
        return _json(200, {"ok": True, "job": Queue.job_dict(j)})
    return _serve(params, go)


def _cancel(j):
    if j["status"] == "cancelled":
        return _json(200, {"ok": True, "job": Queue.job_dict(j)})
    if not Queue.cancel(j):
        return _json(409, {"ok": False, "error": "This job is %s, so it can't be cancelled any more." % j["status"]})
    return _json(200, {"ok": True, "job": Queue.job_dict(j)})


@anvil.server.http_endpoint("/v1/jobs/:job_id/cancel", methods=["POST"])
def api_job_cancel(job_id, **params):
    def go(client):
        j = Queue.find(job_id, client)
        if j is None:
            return _json(404, {"ok": False, "error": "No job %s for this key." % C.text(job_id, 40)})
        return _cancel(j)
    return _serve(params, go)


@anvil.server.http_endpoint("/v1/jobs/:job_id/result", methods=["GET"])
def api_job_result(job_id, **params):
    def go(client):
        j = Queue.find(job_id, client)
        if j is None:
            return _json(404, {"ok": False, "error": "No job %s for this key." % C.text(job_id, 40)})
        if j["status"] != "done" or j["result"] is None:
            return _json(409, {"ok": False, "error": "The picture isn't ready: the job is %s." % j["status"],
                               "job": Queue.job_dict(j)})
        return _media(j["result"], j["result_key"])
    return _serve(params, go)


def _media(m, etag):
    if _header("if-none-match").strip('"') == etag:
        return anvil.server.HttpResponse(304, "", headers={"ETag": '"%s"' % etag})
    return anvil.server.HttpResponse(200, m, headers={"Content-Type": m.content_type, "ETag": '"%s"' % etag,
                                                      "Cache-Control": "private, max-age=86400",
                                                      "X-Content-Type-Options": "nosniff"})


@anvil.server.http_endpoint("/v1/files/:file_key", methods=["GET"])
def api_file(file_key, **params):
    """A picture by its unguessable key: the result once done, or the picture that was sent."""
    if not isinstance(file_key, str) or len(file_key) < 20:
        return _json(404, {"ok": False, "error": "No such picture."})
    j = app_tables.jobs.get(result_key=file_key)
    if j is not None and j["result"] is not None:
        return _media(j["result"], file_key)
    j = app_tables.jobs.get(source_key=file_key)
    if j is not None and j["source"] is not None:
        return _media(j["source"], file_key)
    return _json(404, {"ok": False, "error": "No such picture (it may have been deleted)."})
