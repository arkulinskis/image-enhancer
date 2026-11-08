"""Image Enhancer client for your other Anvil apps. Copy this file into the app's server_code (any name; the
examples use enhancer_client), and add two Secrets in that app (App -> Secrets):

    image_enhancer_key              the API key from the Image Enhancer console (Apps & keys)
    image_enhancer_webhook_secret   (only if you use callback_url) the webhook secret shown with the key

Then, in server code:

    from . import enhancer_client as enhancer

    job = enhancer.submit(media, "kids_book", ref=str(order_id))      # {"id": "job_...", "status": "queued",
                                                                     #  "position": 3, "eta_seconds": 240, ...}
    job = enhancer.status(job["id"])                                 # ask again later (or use wait / a webhook)
    if job["status"] == "done":
        row["styled"] = enhancer.result(job["id"])                   # an Anvil Media, ready for a media column

    enhancer.queue()                                                 # {"queue_length", "pc_online", "eta_new_job_seconds", ...}
    enhancer.styles()                                                # [{"key", "label", "description"}, ...]

    # in a background task: wait until it's done (each call waits up to 20 s on the service)
    job = enhancer.wait(job["id"], timeout=600)

    # webhooks: pass callback_url="https://<your app>/_/api/enhancer-done" to submit(), then
    @anvil.server.http_endpoint("/enhancer-done", methods=["POST"])
    def enhancer_done(**kw):
        payload = enhancer.verified_webhook()     # raises PermissionError if the signature is wrong
        job = payload["job"]                      # payload["event"] is "job.done" or "job.failed"
        ...

Statuses: queued -> working -> done | failed (or cancelled). Times are ISO strings in UTC.
Never call this from client (browser) code: the key must stay on the server.
"""
import base64
import hashlib
import hmac
import json
import time

import anvil
import anvil.http
import anvil.secrets
import anvil.server

# The Image Enhancer app's API address. Change it if the app moves to its own domain.
API = "https://image-enhancer.anvil.app/_/api/v1"


class EnhancerError(Exception):
    """The service said no (bad picture, unknown style, limit reached...). .status = the HTTP code."""
    def __init__(self, status, message):
        Exception.__init__(self, message)
        self.status = status


def _key():
    return anvil.secrets.get_secret("image_enhancer_key")


def _call(method, path, data=None, raw=False, timeout=40):
    headers = {"Authorization": "Bearer " + _key()}
    kw = {}
    if data is not None:
        headers["Content-Type"] = "application/json"
        kw["data"] = json.dumps(data)
    try:
        r = anvil.http.request(API + path, method=method, headers=headers, timeout=timeout, **kw)
    except anvil.http.HttpError as e:
        body = getattr(e, "content", None)
        try:
            text = body.get_bytes().decode("utf-8") if hasattr(body, "get_bytes") else (body or "")
            message = json.loads(text).get("error") or text
        except Exception:
            message = str(e)
        raise EnhancerError(getattr(e, "status", 0), message)
    if raw:
        return r
    text = r.get_bytes().decode("utf-8") if hasattr(r, "get_bytes") else r
    return json.loads(text)


def submit(picture, style, prompt="", fidelity="balanced", megapixels=1.0, size="model", fmt="png", seed=None,
           ref=None, callback_url=None):
    """Send a picture (an Anvil Media, or bytes) to be repainted in `style`. Returns the job dict."""
    data = picture.get_bytes() if hasattr(picture, "get_bytes") else bytes(picture)
    body = {"image": base64.b64encode(data).decode("ascii"), "style": style, "prompt": prompt, "fidelity": fidelity,
            "megapixels": megapixels, "size": size, "format": fmt, "filename": getattr(picture, "name", None) or "picture.png"}
    for k, v in (("seed", seed), ("ref", ref), ("callback_url", callback_url)):
        if v is not None:
            body[k] = v
    return _call("POST", "/jobs", body)["job"]


def status(job_id):
    """The job now: status, position, eta_seconds / eta_at, result_url when done, error when failed."""
    return _call("GET", "/jobs/%s" % job_id)["job"]


def wait(job_id, timeout=600):
    """Wait until the job is done, failed or cancelled (or timeout seconds pass). Use in a background task."""
    end = time.time() + timeout
    job = status(job_id)
    while job["status"] in ("queued", "working") and time.time() < end:
        job = _call("GET", "/jobs/%s?wait=20" % job_id, timeout=40)["job"]
    return job


def result(job_id):
    """The finished picture as an Anvil Media (raises EnhancerError 409 if it isn't ready)."""
    return _call("GET", "/jobs/%s/result" % job_id, raw=True, timeout=60)


def cancel(job_id):
    return _call("POST", "/jobs/%s/cancel" % job_id)["job"]


def queue():
    return _call("GET", "/queue")


def styles():
    return _call("GET", "/styles")["styles"]


def verified_webhook():
    """Inside your http_endpoint: check the X-Enhancer-Signature header, return the JSON payload."""
    req = anvil.server.request
    body = req.body.get_bytes() if hasattr(req.body, "get_bytes") else (req.body or b"")
    if isinstance(body, str):
        body = body.encode("utf-8")
    secret = anvil.secrets.get_secret("image_enhancer_webhook_secret")
    good = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    sent = ""
    for k, v in (req.headers or {}).items():
        if k.lower() == "x-enhancer-signature":
            sent = v or ""
    if not hmac.compare_digest(good, sent):
        raise PermissionError("This call didn't come from Image Enhancer (bad signature).")
    return json.loads(body.decode("utf-8"))
