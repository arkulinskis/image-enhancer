"""End to end through Anvil Uplink, on the local App Server (started by tools/ui_test.py with --uplink-key):

    the real worker (worker/enhancer_worker.py) + the fake ComfyUI (worker/tests/fake_comfy.py) + the app's HTTP API.

    <python with anvil-uplink + pillow> tools/testing/e2e_uplink.py     -> E2E PASSED

1. an API key is added through Uplink (server key = full access, like the console would);
2. the worker connects; a picture sent to POST /v1/jobs comes back restyled (the fake inverts the colours), the
   webhook-free job reports done, GET /result returns the picture;
3. the worker stops: the next picture waits and the app schedules a retry ("PC away");
4. the worker starts again: its hello starts the waiting picture at once (no 15-minute wait).
"""
import hashlib
import io
import json
import os
import pathlib
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "worker" / "tests"), str(ROOT / "tools")]
import ui_test  # noqa: E402  (port, URL, uplink key of the local App Server)
from fake_comfy import FAKE, start_fake  # noqa: E402
from PIL import Image  # noqa: E402

API = ui_test.URL + "/_/api/v1"
UPLINK = ui_test.URL.replace("http://", "ws://") + "/_/uplink"


def http(method, path, key, body=None, ctype="application/json"):
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Authorization": "Bearer " + key, **({"Content-Type": ctype} if data else {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if r.headers.get("Content-Type", "").startswith("application/json") else raw)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def picture():
    im = Image.new("RGB", (480, 360), (40, 120, 200))
    for x in range(100, 380):
        for y in range(200, 300):
            im.putpixel((x, y), (250, 200, 30))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def start_worker(cfg_path, comfy_url):
    log = open(str(cfg_path) + ".log", "ab")
    return subprocess.Popen([sys.executable, str(ROOT / "worker" / "enhancer_worker.py"), "--key", ui_test.UPLINK_KEY,
                             "--url", UPLINK, "--comfy-url", comfy_url, "--backend", "comfyui"],
                            env=dict(os.environ, IE_WORKER_CONFIG=str(cfg_path)), stdout=log, stderr=subprocess.STDOUT)


def wait_for(fn, what, seconds=90):
    end = time.time() + seconds
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(1.5)
    raise AssertionError("timed out: " + what)


def main():
    ui_test.start()
    srv, comfy = start_fake()
    tmp = pathlib.Path(tempfile.mkdtemp())
    cfg = tmp / "config.json"
    cfg.write_text(json.dumps({"start_comfy": False, "comfy_dir": str(tmp), "heartbeat_seconds": 20}))

    import anvil.server
    anvil.server.connect(ui_test.UPLINK_KEY, url=UPLINK, quiet=True)
    from anvil.tables import app_tables
    key = "ie_" + secrets.token_hex(20)
    app_tables.clients.add_row(name="E2E " + key[-6:], key_prefix=key[:9], key_hash=hashlib.sha256(key.encode()).hexdigest(),
                               webhook_secret="whsec_test", active=True, hourly_limit=100, jobs_total=0, is_demo=False,
                               created=__import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    print("ok   API key added through Uplink")

    w = start_worker(cfg, comfy)
    try:
        wait_for(lambda: (anvil.server.call("enhancer_worker_hello", {"backend": "test"}) or True) and
                 any("Connected" in l for l in open(str(cfg) + ".log", encoding="utf-8", errors="replace")), "worker connected", 120)
        print("ok   the worker connected over Uplink")
        s, d = http("POST", "/jobs", key, {"image": __import__("base64").b64encode(picture()).decode(), "style": "kids_book",
                                             "fidelity": "strict", "megapixels": 0.5, "seed": 77, "ref": "e2e-1"})
        assert s == 202, (s, d)
        jid = d["job"]["id"]
        job = wait_for(lambda: (lambda r: r[1]["job"] if r[1]["job"]["status"] in ("done", "failed") else None)(http("GET", "/jobs/" + jid, key)), "job done", 120)
        assert job["status"] == "done", job
        assert job["seed"] == 77 and job["result_url"], job
        p = [x for x in FAKE["prompts"] if any(n["inputs"].get("noise_seed") == 77 for n in x.values())]
        assert p and "exact composition" in [n for n in p[-1].values() if n["class_type"] == "CLIPTextEncode"][0]["inputs"]["text"]
        s, raw = http("GET", "/jobs/%s/result" % jid, key)
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        r, g, b = im.getpixel((5, 5))
        assert s == 200 and r > 180 and b < 90, ("the fake inverts the colours", im.getpixel((5, 5)))
        print("ok   picture -> API -> dispatcher -> Uplink -> worker -> ComfyUI -> back (%s s, %dx%d)" % (job["seconds"], im.size[0], im.size[1]))

        w.terminate()
        w.wait(20)
        time.sleep(2)
        s, d = http("POST", "/jobs?style=watercolor&format=webp", key, picture(), "image/png")
        assert s == 202, d
        jid2 = d["job"]["id"]
        job2 = wait_for(lambda: (lambda j: j if j.get("next_try_at") else None)(http("GET", "/jobs/" + jid2, key)[1]["job"]), "PC away", 90)
        assert job2["status"] == "queued" and job2["eta_seconds"] > 600, job2
        print("ok   worker stopped: the picture waits, retry at %s" % job2["next_try_at"])

        t0 = time.time()
        w = start_worker(cfg, comfy)
        job2 = wait_for(lambda: (lambda j: j if j["status"] == "done" else None)(http("GET", "/jobs/" + jid2, key)[1]["job"]), "done after hello", 150)
        print("ok   worker back: hello started the waiting picture at once (%.0f s, no 15-minute wait)" % (time.time() - t0))
        s, d = http("GET", "/queue", key)
        assert d["pc_online"] is True and d["pc_next_try_at"] is None, d
        print("ok   GET /queue: PC online again")
    finally:
        w.terminate()
        srv.shutdown()
    print("E2E PASSED")


if __name__ == "__main__":
    main()
