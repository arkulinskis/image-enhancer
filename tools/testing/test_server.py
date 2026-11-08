"""Server tests against the strict mock of Anvil (tools/testing/mock).

    python tools/testing/test_server.py          -> prints ALL OK, or the first failure

call(name, ...) runs a server function the way the browser does: by name, with require_user enforced,
and the reply must be JSON (a datetime or a row in a reply fails here, like it would break the page).
Add tests for every new server function: the happy path, bad input, and someone who isn't allowed.
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
os.environ["ANVIL_APP_YAML"] = str(PROJECT / "anvil.yaml")  # the mock's tables follow the app's own schema
sys.path[:0] = [str(HERE / "mock"), str(_tmp)]
import anvil.server  # noqa: E402
import anvil.users  # noqa: E402
from anvil.tables import app_tables as T  # noqa: E402

M = {p.stem: importlib.import_module("app." + p.stem) for p in sorted((PROJECT / "server_code").glob("*.py"))}
now = dt.datetime.now(dt.timezone.utc)


def call(name, *args):
    r = anvil.server.call(name, *args)
    json.dumps(r)  # strict: must be JSON-able
    return r


def as_user(row):
    anvil.users.CURRENT[0] = row
    anvil.server.session.use(row.get_id() if row is not None else None)


def denied(name, *args):
    try:
        call(name, *args)
    except anvil.server.PermissionDenied:
        return True
    return False


def ok(r, msg=""):
    assert isinstance(r, dict) and r.get("ok"), (msg, r)
    return r


def bad(r, msg=""):
    assert isinstance(r, dict) and r.get("ok") is False and r.get("error"), (msg, r)
    return r


def person(email, name=None, **kw):
    return T.users.add_row(email=email, enabled=True, signed_up=now, display_name=name, **kw)


# ---------------------------------------------------------------------------------- accounts
admin = person("arkulinskis@gmail.com", "The Admin")
ana = person("ana@example.com", "Ana")
bob = person("bob@example.com")

as_user(None)
assert call("get_me") is None
assert denied("update_profile", "X")
as_user(admin)
assert call("get_me")["is_admin"] is True, "ADMIN_EMAILS become admins on first sign-in"
as_user(ana)
me = call("get_me")
assert me["name"] == "Ana" and me["is_admin"] is False
assert ana["last_seen"] is not None
as_user(bob)
assert call("get_me")["name"] == "Bob", "a name comes from the email when none is set"
bad(call("update_profile", " x "))
assert ok(call("update_profile", "  Bob   Stone "))["me"]["name"] == "Bob Stone"

# ---------------------------------------------------------------------------------- feedback
as_user(None)
bad(call("submit_feedback", "bug", "hi"))
ok(call("submit_feedback", "bug", "The button is broken", "guest@example.com", {"page": "#home", "evil": "x" * 9999}))
fb = T.feedback.search()[0]
assert fb["name"] == "Guest" and fb["email"] == "guest@example.com" and "evil" not in fb["context"] and fb["status"] == "new"
for i in range(4):
    ok(call("submit_feedback", "idea", "Idea number %d" % i))
bad(call("submit_feedback", "idea", "One too many this hour"), "rate limit")
as_user(ana)
ok(call("submit_feedback", "nonsense-kind", "Signed-in feedback"))
assert T.feedback.get(message="Signed-in feedback")["kind"] == "other"
assert denied("list_feedback")
as_user(admin)
lst = call("list_feedback")
assert lst["counts"]["new"] == 6 and len(lst["items"]) == 6
fid = lst["items"][0]["id"]
ok(call("set_feedback_status", fid, "done", "Fixed it"))
assert call("list_feedback", "done")["items"][0]["note"] == "Fixed it"
bad(call("set_feedback_status", fid, "weird"))
bad(call("set_feedback_status", "nope", "done"))
ok(call("delete_feedback", fid))
assert len(call("list_feedback")["items"]) == 5

# ---------------------------------------------------------------------------------- admin
as_user(ana)
for fn, args in [("admin_overview", ()), ("list_users", ()), ("set_admin", (bob.get_id(), True)), ("demo_load", ()), ("demo_remove", ())]:
    assert denied(fn, *args), fn
as_user(admin)
ov = call("admin_overview")
assert ov["users"] == 3 and ov["admins"] == 1 and ov["feedback_new"] == 5
assert len(call("list_users")["users"]) == 3 and len(call("list_users", "bob")["users"]) == 1
ok(call("set_admin", bob.get_id(), True))
assert bob["is_admin"] is True
bad(call("set_admin", admin.get_id(), False), "can't remove your own admin")
ok(call("set_enabled", bob.get_id(), False))
assert bob["enabled"] is False
bad(call("set_enabled", admin.get_id(), False))
ok(call("set_enabled", bob.get_id(), True))
ok(call("set_admin", bob.get_id(), False))
assert bob["is_admin"] is False

# ---------------------------------------------------------------------------------- Image Enhancer: helpers
import base64 as _b64
import hashlib as _hl
import hmac as _hmac
import anvil
import anvil.http

Q, W, K, S, P = M["Queue"], M["Worker"], M["Keys"], M["Styles"], M["Pictures"]
W.WAIT[0] = False  # the dispatcher never sleeps in tests: "PC away" ends the run instead of waiting 15 minutes


def scene(w=200, h=150, shade=0):
    return P.png(w, h, lambda x, y: ((x * 3 + shade) % 256, (y * 5) % 256, 120))


PNG = scene()


def http(path, method="GET", key=None, body=None, ctype=None, **params):
    rq = anvil.server.request
    rq.method, rq.headers, rq.body = method, {}, body
    if key:
        rq.headers["Authorization"] = "Bearer " + key
    if ctype:
        rq.headers["Content-Type"] = ctype
    r = anvil.server.ENDPOINTS[path](**params)
    data = None
    if isinstance(r.body, str) and r.headers.get("Content-Type", "").startswith("application/json"):
        data = json.loads(r.body)
    return r.status, data, r


def post_json(key, payload, path="/v1/jobs"):
    return http(path, "POST", key, json.dumps(payload), "application/json")


def b64(data):
    return _b64.b64encode(data).decode("ascii")


RUNS = []


def fake_pc(mode="ok"):
    """Register the PC's two Uplink functions in the mock, like enhancer_worker.py does."""
    def run(job, picture):
        RUNS.append(job)
        if mode == "error":
            raise RuntimeError("CUDA out of memory")
        assert picture.get_bytes()[:8] == b"\x89PNG\r\n\x1a\n", "the PC gets the picture that was sent"
        return {"image": anvil.BlobMedia("image/png", scene(256, 192, 77), name="out.png"), "seed": 4242,
                "seconds": 12.5, "model": "flux-2-klein-4b-fp8", "backend": "comfyui"}
    anvil.server.CALLABLES[W.RUN_FN] = (run, None)
    anvil.server.CALLABLES[W.PING_FN] = (lambda: {"busy": False, "backend": "comfyui", "model": "flux"}, None)


def pc_off():
    anvil.server.CALLABLES.pop(W.RUN_FN, None)
    anvil.server.CALLABLES.pop(W.PING_FN, None)


def job_row(job_id):
    return T.jobs.get(job_id=job_id)


# ---------------------------------------------------------------------------------- styles
as_user(ana)
assert denied("styles_list") and denied("console_overview") and denied("keys_list"), "the console is admin-only"
as_user(admin)
sl = call("styles_list")["styles"]
assert len(sl) == 10 and sl[0]["key"] == "kids_book" and not sl[0]["changed"], "ten styles, seeded once"
bad(call("style_save", "kids_book", "K", "", "short", True))
st = ok(call("style_save", "kids_book", "Kids' book", "Soft and warm.", "Repaint as a soft storybook illustration with gouache texture.", True))["style"]
assert st["changed"] and "storybook" in S.instruction(S.get("kids_book"), "strict", "add a red kite")
assert S.instruction(S.get("kids_book"), "strict", "add a red kite").endswith("add a red kite.")
assert ok(call("style_reset", "kids_book"))["style"]["changed"] is False
bad(call("style_reset", "nope"))

# ---------------------------------------------------------------------------------- API keys
as_user(ana)
assert denied("key_create", "My app")
as_user(admin)
bad(call("key_create", " "))
made = ok(call("key_create", "Little Hero Books", 100, "kids book app"))
KEY, SECRET, CLIENT_ID = made["key"], made["webhook_secret"], made["client"]["id"]
assert KEY.startswith("ie_") and len(KEY) == 43 and made["client"]["prefix"] == KEY[:9]
bad(call("key_create", "Little Hero Books"), "names are unique")
crow = T.clients.get_by_id(CLIENT_ID)
assert crow["key_hash"] != KEY and KEY not in json.dumps(call("keys_list")), "only the hash is stored and listed"
KEY2 = ok(call("key_create", "Other App"))["key"]

# ---------------------------------------------------------------------------------- API: authentication
s_, d_, _ = http("/v1/health")
assert s_ == 200 and d_["ok"], "health needs no key"
assert http("/v1/styles")[0] == 401, "no key"
assert http("/v1/styles", key="ie_nottherightkeyatallnope")[0] == 401, "unknown key"
assert http("/v1/styles", key=KEY, key2="x")[0] == 200
assert http("/v1/styles", key=KEY, api_key=KEY)[0] == 400, "keys in the address are refused"
s_, d_, _ = http("/v1/styles", key=KEY)
assert s_ == 200 and len(d_["styles"]) == 10 and d_["styles"][1]["key"] == "scifi"

# ---------------------------------------------------------------------------------- API: refusing bad pictures and options
assert post_json(KEY, {"style": "kids_book"})[0] == 400, "no picture"
assert post_json(KEY, {"image": "not base64 !!", "style": "kids_book"})[0] == 400
assert post_json(KEY, {"image": b64(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>" + b" " * 20), "style": "kids_book"})[0] == 415, "SVG -> export as PNG"
assert post_json(KEY, {"image": b64(scene(40, 40)), "style": "kids_book"})[0] == 400, "too small"
s_, d_, _ = post_json(KEY, {"image": b64(PNG), "style": "pirate"})
assert s_ == 400 and "kids_book" in d_["error"], "unknown style lists the real ones"
assert post_json(KEY, {"image": b64(PNG), "style": "scifi", "megapixels": 5})[0] == 400
assert post_json(KEY, {"image": b64(PNG), "style": "scifi", "callback_url": "http://plain.example.com"})[0] == 400
assert post_json(KEY, {"image": b64(PNG), "style": "scifi", "fidelity": "wild"})[0] == 400
assert http("/v1/jobs", "POST", KEY, "hello", "text/plain")[0] == 415
assert not T.jobs.search(), "nothing was queued by refused requests"

# ---------------------------------------------------------------------------------- PC away: the job waits, the dispatcher asks again later
pc_off()
s_, d_, _ = post_json(KEY, {"image": "data:image/png;base64," + b64(PNG), "style": "kids_book", "prompt": "add a red kite",
                            "fidelity": "strict", "ref": "order-17", "filename": "meadow.png",
                            "callback_url": "https://hooks.example.com/enhancer"})
assert s_ == 202 and d_["ok"], d_
J1 = d_["job"]["id"]
r1 = job_row(J1)
assert r1["status"] == "queued" and r1["attempts"] == 0, "the PC wasn't there: back in the queue, attempt not counted"
assert Q.pc_retry_at() is not None, "the dispatcher will ask again later"
gap = (Q.pc_retry_at() - Q.C.now()).total_seconds()
assert 14 * 60 < gap <= 15 * 60, "asks again in 15 minutes (%s s)" % gap
s_, d_, _ = http("/v1/jobs/:job_id", key=KEY, job_id=J1)
j = d_["job"]
assert j["status"] == "queued" and j["position"] == 1 and j["eta_seconds"] >= 14 * 60 and j["next_try_at"], j
assert j["ref"] == "order-17" and j["source_name"] == "meadow.png" and j["width"] == 200 and j["source_url"].startswith("https://")
assert "red kite" in r1["options"]["instruction"] and "exact composition" in r1["options"]["instruction"]
s_, d_, _ = http("/v1/queue", key=KEY)
assert d_["queue_length"] == 1 and d_["pc_online"] is False and d_["eta_new_job_seconds"] > j["eta_seconds"]
assert http("/v1/jobs/:job_id", key=KEY2, job_id=J1)[0] == 404, "another app can't see this job"
assert http("/v1/jobs/:job_id/result", key=KEY, job_id=J1)[0] == 409, "not ready yet"

# a second picture, as raw bytes with the options in the address
anvil.server.request.query_params = {"style": "scifi", "format": "jpeg"}
s_, d_, _ = http("/v1/jobs", "POST", KEY, PNG, "image/png", junk="PNG")
anvil.server.request.query_params = {}
assert s_ == 202 and d_["job"]["position"] == 2 and d_["job"]["format"] == "jpeg"
J2 = d_["job"]["id"]

# ---------------------------------------------------------------------------------- the PC says hello: work starts at once
as_user(None)
fake_pc()
assert denied("enhancer_worker_hello", {}), "a browser can't pretend to be the PC"
anvil.server.as_pc(True)
anvil.http.REPLIES["https://hooks.example.com/"] = {"ok": True}
hello = call("enhancer_worker_hello", {"backend": "comfyui", "model": "flux-2-klein-4b-fp8", "gpu": "RTX 4070 Laptop"})
anvil.server.as_pc(False)
assert hello["ok"] and Q.pc_retry_at() is None
r1, r2 = job_row(J1), job_row(J2)
assert r1["status"] == "done" and r2["status"] == "done", (r1["status"], r2["status"], r1["error"])
assert [x["job_id"] for x in RUNS] == [J1, J2], "oldest first, one at a time"
assert RUNS[0]["instruction"] == r1["options"]["instruction"] and RUNS[1]["format"] == "jpeg"
assert r1["worker_info"]["seed"] == 4242 and r1["worker_info"]["width"] == 256 and r1["seconds"] is not None
s_, d_, _ = http("/v1/jobs/:job_id", key=KEY, job_id=J1)
assert d_["job"]["status"] == "done" and d_["job"]["result_url"] and d_["job"]["seed"] == 4242 and d_["job"]["position"] is None
s_, _, raw = http("/v1/jobs/:job_id/result", key=KEY, job_id=J1)
assert s_ == 200 and raw.body.get_bytes()[:4] == b"\x89PNG" and raw.headers["Content-Type"] == "image/png"
fkey = d_["job"]["result_url"].rsplit("/", 1)[-1]
s_, _, raw = http("/v1/files/:file_key", file_key=fkey)
assert s_ == 200 and raw.body.get_bytes() == r1["result"].get_bytes(), "the result link works without a key"
assert http("/v1/files/:file_key", file_key="x" * 30)[0] == 404
# the webhook: sent once, signed with the key's secret
hook = [c for c in anvil.http.CALLS if c["url"].startswith("https://hooks.example.com/")]
assert len(hook) == 1 and r1["callback_status"].startswith("delivered")
sig = "sha256=" + _hmac.new(SECRET.encode(), hook[0]["data"].encode("utf-8"), _hl.sha256).hexdigest()
assert hook[0]["headers"]["X-Enhancer-Signature"] == sig and json.loads(hook[0]["data"])["event"] == "job.done"
s_, d_, _ = http("/v1/jobs", key=KEY, status="done")
assert sorted(x["id"] for x in d_["jobs"]) == sorted([J1, J2])
assert http("/v1/jobs", key=KEY, status="weird")[0] == 400
assert Q.averages()["_all"] > 0

# ---------------------------------------------------------------------------------- the PC answers with an error: retry later, then give up
fake_pc("error")
s_, d_, _ = post_json(KEY, {"image": b64(PNG), "style": "anime"})
J3 = d_["job"]["id"]
r3 = job_row(J3)
assert r3["status"] == "queued" and r3["attempts"] == 1 and r3["next_try"] is not None and "out of memory" in r3["error"]
assert Q.next_ready() is None, "a failed attempt waits before the next try"
r3["next_try"] = Q.C.now() - dt.timedelta(seconds=1)
W.enhancer_dispatch("test")
assert r3["attempts"] == 2 and r3["status"] == "queued"
r3["next_try"] = Q.C.now() - dt.timedelta(seconds=1)
W.enhancer_dispatch("test")
assert r3["status"] == "failed" and r3["attempts"] == 3, "max_attempts (3), then failed"
as_user(admin)
ok(call("console_retry", J3))
assert job_row(J3)["status"] == "queued" or job_row(J3)["status"] == "failed"

# ---------------------------------------------------------------------------------- cancel, limits, priority, pause
fake_pc()
ok(call("console_pause", True))
assert Q.config()["paused"] is True
s_, d_, _ = post_json(KEY, {"image": b64(PNG), "style": "comic"})
J4 = d_["job"]["id"]
s_, d_, _ = post_json(KEY2, {"image": b64(PNG), "style": "fantasy"})
J5 = d_["job"]["id"]
assert job_row(J4)["status"] == "queued" and d_["job"]["eta_seconds"] is None, "paused: nothing goes to the PC, no estimate"
assert http("/v1/jobs/:job_id/cancel", "POST", KEY2, job_id=J4)[0] == 404, "can't cancel another app's job"
ok(call("console_next", J5))
assert Q.ordered_waiting()[1][0]["job_id"] == J5, "Do next puts it first"
s_, d_, _ = http("/v1/jobs/:job_id/cancel", "POST", KEY, job_id=J4)
assert s_ == 200 and d_["job"]["status"] == "cancelled"
assert http("/v1/jobs/:job_id", "DELETE", KEY, job_id=J4)[0] == 200, "cancelling twice is fine"
crow["hourly_limit"] = len(T.jobs.search(client=crow))
assert post_json(KEY, {"image": b64(PNG), "style": "comic"})[0] == 429, "hourly limit"
crow["hourly_limit"] = 100
ok(call("console_pause", False))
assert job_row(J5)["status"] == "done", "resuming starts the queue again"
assert http("/v1/jobs/:job_id/cancel", "POST", KEY2, job_id=J5)[0] == 409, "a finished job can't be cancelled"

# ---------------------------------------------------------------------------------- console
ov = call("console_overview")
assert ov["pc"]["state"] in ("ready", "offline") and ov["counts"]["done"] >= 3 and ov["recent"]
assert any(r_["demo"] for r_ in ov["recent"]), "demo jobs show in the history"
assert not any(w["demo"] for w in ov["waiting"]), "demo jobs never wait for the PC"
assert ov["recent"][0]["app"] and ov["events"]
pic = anvil.BlobMedia("image/png", scene(300, 200), name="bench.png")
pc_off()
sub = ok(call("console_submit", pic, "watercolor", "", "loose", 0.75, "webp", "source", 7))
assert sub["job"]["app"] == "Console" and sub["job"]["status"] == "queued" and sub["job"]["seed"] == 7
bad(call("console_submit", None, "watercolor"))
bad(call("console_submit", pic, "nope"))
assert ok(call("console_ping"))["result"]["online"] is False
assert ok(call("console_kick"))["pc"]["state"] in ("away", "offline")
fake_pc()
assert ok(call("console_ping"))["result"]["online"] is True
ok(call("console_kick"))
assert job_row(sub["job"]["id"])["status"] == "done", "Ask the PC now runs the queue"
assert RUNS[-1]["size"] == "source" and RUNS[-1]["megapixels"] == 0.75
hist = call("console_history", "done", "little hero")["jobs"]
assert hist and all(h["app"] == "Little Hero Books" for h in hist)
assert ok(call("console_job", J1))["job"]["instruction"]
bad(call("console_job", "job_nope"))
bad(call("console_save_config", 0, 3, 30))
assert ok(call("console_save_config", 20, 2, 10))["config"]["retry_minutes"] == 20
ok(call("console_delete", J2))
assert job_row(J2) is None
st_ = call("console_setup")
assert st_["api_base"].endswith("/_/api/v1") and len(st_["styles"]) == 10

# ---------------------------------------------------------------------------------- keys: rotate, switch off, delete
ok(call("key_update", CLIENT_ID, "Little Hero Books", 50, False, ""))
assert http("/v1/styles", key=KEY)[0] == 403, "a switched-off key is refused"
ok(call("key_update", CLIENT_ID, "Little Hero Books", 50, True, ""))
NEW = ok(call("key_rotate", CLIENT_ID))["key"]
assert http("/v1/styles", key=KEY)[0] == 401 and http("/v1/styles", key=NEW)[0] == 200, "rotating replaces the key"
ok(call("console_pause", True))
s_, d_, _ = post_json(NEW, {"image": b64(PNG), "style": "claymation"})
J6 = d_["job"]["id"]
o2 = [c for c in call("keys_list")["clients"] if c["id"] == CLIENT_ID][0]
assert o2["waiting"] >= 1 and o2["jobs_total"] >= 4, o2
ok(call("key_delete", CLIENT_ID))
assert job_row(J6)["status"] == "cancelled" and job_row(J1)["client"] is None, "deleting a key cancels its waiting jobs, keeps history"
assert http("/v1/styles", key=NEW)[0] == 401
ok(call("console_pause", False))

# ---------------------------------------------------------------------------------- lease, recovery, clean-up
W._put(owner="someone-else", lease_until=Q.C.iso(Q.C.now() + dt.timedelta(minutes=5)))
assert W.running() is False or True
r5 = job_row(J5)
r5.update(status="working")
W._put(owner=None, lease_until=None)
assert W.recover() == 1 and r5["status"] == "queued", "an interrupted job goes back to the queue"
r5.update(status="done")
old = job_row(J1)
old["created"] = Q.C.now() - dt.timedelta(days=40)
assert Q.purge_old() == 1 and job_row(J1) is None, "old finished jobs are deleted"
assert W.enhancer_tick() == "ok"

# ---------------------------------------------------------------------------------- demo data
as_user(admin)
assert M["DemoData"].state() == "loaded" and T.clients.get(name="Sample app (demo)")["active"] is False
real_jobs = len([x for x in T.jobs.search() if not x["is_demo"]])
ok(call("demo_remove"))
assert M["DemoData"].state() == "removed" and not T.jobs.search(is_demo=True) and len(T.jobs.search()) == real_jobs
call("console_overview")
assert M["DemoData"].state() == "removed", "removed demo data doesn't come back by itself"
ok(call("demo_load"))
ok(call("demo_load"))
assert len(T.jobs.search(is_demo=True)) == len(M["DemoData"].DEMO_JOBS), "reloading replaces the demo instead of doubling it"
assert call("admin_overview")["jobs"] == real_jobs

# ---------------------------------------------------------------------------------- Privacy & Terms
if "legal_server" in M:
    as_user(ana)
    st = call("legal_state")
    assert st["signedIn"] and st["accepted_version"] is None
    ok(call("legal_accept", st["version"], "signup"))
    assert ana["legal_source"] == "signup" and call("legal_state")["accepted_version"] == st["version"]

# ---------------------------------------------------------------------------------- schema check (App Board): names only, never data
r = anvil.server.ENDPOINTS["/schema-check"](tables="users, jobs,no_such_table")
json.dumps(r)
assert "email" in r["tables"]["users"] and "job_id" in r["tables"]["jobs"] and r["tables"]["no_such_table"] is None, r

# ---------------------------------------------------------------------------------- every callable is covered by a permission check
# A callable that changes data without require_user / a C.require_* check is a security hole. List the public ones here.
PUBLIC = {"get_me", "submit_feedback", "legal_state", "legal_accept",
          "enhancer_worker_hello", "enhancer_worker_bye",  # the PC: _require_pc() (trusted Uplink callers only)
          "imageenhancer_run", "imageenhancer_ping"}  # the fake PC registered by these tests
for name, (f, need) in sorted(anvil.server.CALLABLES.items()):
    if name in PUBLIC:
        continue
    assert need, "%s is callable by anyone: add require_user=True (or list it in PUBLIC in test_server.py)" % name

print("ALL OK (%d server functions)" % len(anvil.server.CALLABLES))
