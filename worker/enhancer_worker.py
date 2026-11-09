"""Image Enhancer worker: links this PC's ComfyUI to the Image Enhancer app through Anvil Uplink.

    start_worker.bat                      (Windows: runs this with the worker's own Python environment)
    python enhancer_worker.py [--backend comfyui|classic] [--key server_...] [--url ws://localhost:3100/_/uplink]
                              [--check]   just check ComfyUI and the model files, then exit
                              [--new-key] forget the saved Uplink key and ask for it again

What it does:
  - connects to the app with the SERVER Uplink key (saved in config.json the first time you paste it);
  - registers imageenhancer_run(job, picture): the app calls it with one picture at a time; the worker repaints it
    (engines.py: ComfyUI + FLUX.2 [klein] 4B, or the classic test filters) and returns the result;
  - registers imageenhancer_ping(): the console's "Check the PC" button;
  - says hello when it connects and every couple of minutes, so the app knows the PC is there (and starts any
    waiting pictures at once instead of after its 15-minute wait);
  - says bye when you close it.
Only one picture is ever painted at a time (a lock), whatever the app sends.
"""
import argparse
import atexit
import datetime
import getpass
import json
import os
import platform
import socket
import sys
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engines  # noqa: E402

VERSION = "1.0.0"
CONFIG = os.environ.get("IE_WORKER_CONFIG") or os.path.join(HERE, "config.json")
DEFAULTS = {
    "uplink_key": "",
    "anvil_url": "",                      # empty = hosted Anvil (anvil.works); a local App Server: ws://localhost:PORT/_/uplink
    "backend": "comfyui",                 # comfyui | classic
    "comfy_url": "http://127.0.0.1:8188",
    "comfy_dir": "ComfyUI",               # where setup_comfyui.ps1 installed it (relative to this folder)
    "start_comfy": True,                  # start ComfyUI if it isn't running
    "comfy_args": [],                     # extra ComfyUI flags, e.g. ["--lowvram"] on a 6 GB card
    "hide_comfy_window": True,
    "workflow": "workflows/flux2_klein_edit.json",
    "steps": 4,                           # FLUX.2 [klein] distilled is made for 4
    "max_megapixels": 2.0,
    "job_timeout": 900,
    "heartbeat_seconds": 120,
    "tidy_files": True,                   # delete each job's files from ComfyUI's input/output folders
}
LOCK = threading.Lock()
STATE = {"busy": False, "done": 0, "failed": 0, "engine": None, "started": time.time()}


def log(msg):
    line = "%s  %s" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(os.path.join(HERE, "worker.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_config():
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG):
        with open(CONFIG, encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


def save_config(cfg):
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def clean_key(key):
    """The key as Anvil wants it: no spaces, quotes or invisible characters, and only once. The prompt hides what you
    type, so pasting twice is easy (2026-11-09: a key saved twice over was refused as "Incorrect uplink key")."""
    key = "".join(ch for ch in str(key or "") if ch.isprintable() and not ch.isspace()).strip("\"'")
    for n in (2, 3, 4):
        if len(key) % n == 0 and key[:len(key) // n] * n == key:
            return key[:len(key) // n]
    return key


def masked(key):
    return "%s...%s (%d characters)" % (key[:10], key[-3:], len(key)) if len(key) > 16 else "(%d characters)" % len(key)


def ask_key(cfg):
    print("\nPaste the app's SERVER Uplink key (Anvil editor: + Add feature -> Uplink -> Enable the Server Uplink).")
    print("It starts with server_ and is saved only in worker/config.json on this PC.")
    print("The key stays hidden while you paste it: paste it ONCE, then press Enter.")
    for _ in range(3):
        key = clean_key(getpass.getpass("Uplink key (hidden as you type): "))
        if not key:
            sys.exit("No key given.")
        if key.startswith("client_"):
            print("That's the CLIENT key. The worker needs the SERVER key (the other one in Anvil's Uplink window).")
            continue
        if not key.startswith("server_"):
            print("That doesn't look like an Uplink key (it should start with server_). Please paste it again.")
            continue
        cfg["uplink_key"] = key
        save_config(cfg)
        print("Saved: %s" % masked(key))
        return cfg
    sys.exit("No usable key given.")


def wrong_key(e):
    return "uplink key" in str(e).lower()


def stop_wrong_key():
    """Anvil refused the key: say so plainly and stop (the uplink library would otherwise retry forever)."""
    log("Anvil says this Uplink key is wrong. Copy the SERVER key again (Anvil editor: Uplink window), then run")
    log("   start_worker.bat --new-key")
    log("and paste it ONCE. (A new key is needed if someone pressed Reset in Anvil's Uplink window.)")
    os._exit(3)


def worker_info():
    eng = STATE["engine"]
    info = eng.info() if eng else {}
    info.update(version=VERSION, host=socket.gethostname()[:40])
    return info


def hello(server):
    try:
        r = server.call("enhancer_worker_hello", worker_info())
        return r
    except Exception as e:
        if wrong_key(e):
            stop_wrong_key()
        log("Couldn't say hello to the app (%s). Will try again." % type(e).__name__)
        return None


def main():
    ap = argparse.ArgumentParser(description="Image Enhancer worker")
    ap.add_argument("--backend", choices=["comfyui", "classic"])
    ap.add_argument("--key", help="the SERVER Uplink key (saved to config.json)")
    ap.add_argument("--url", help="Uplink address (only for a self-hosted / local Anvil App Server)")
    ap.add_argument("--comfy-url")
    ap.add_argument("--check", action="store_true", help="check ComfyUI + model files, then exit")
    ap.add_argument("--once", action="store_true", help="(tests) exit after the first job")
    ap.add_argument("--new-key", action="store_true", help="forget the saved Uplink key and ask for it again")
    args = ap.parse_args()

    cfg = load_config()
    if cfg.get("uplink_key") and clean_key(cfg["uplink_key"]) != cfg["uplink_key"]:
        cfg["uplink_key"] = clean_key(cfg["uplink_key"])
        save_config(cfg)
        log("Fixed the saved Uplink key (it had been pasted more than once, or had spaces): %s" % masked(cfg["uplink_key"]))
    if args.new_key:
        cfg["uplink_key"] = ""
    if args.key:
        cfg["uplink_key"] = clean_key(args.key)
        save_config(cfg)
    if args.backend:
        cfg["backend"] = args.backend
    if args.url:
        cfg["anvil_url"] = args.url
    if args.comfy_url:
        cfg["comfy_url"] = args.comfy_url

    log("Image Enhancer worker %s on %s (Python %s), engine: %s" % (VERSION, socket.gethostname(), platform.python_version(), cfg["backend"]))
    eng = engines.make(cfg, log)
    STATE["engine"] = eng
    try:
        eng.prepare()
        log("Engine ready: %s" % json.dumps(eng.info()))
    except engines.EngineError as e:
        log("PROBLEM: %s" % e)
        if args.check:
            sys.exit(1)
        log("The worker connects anyway; jobs will fail with this message until it's fixed (the app retries them).")
    if args.check:
        log("Check passed.")
        return

    if not cfg.get("uplink_key"):
        cfg = ask_key(cfg)

    try:
        import anvil.server
        import anvil
    except ImportError:
        sys.exit("The anvil-uplink package isn't installed for this Python. Run setup_comfyui.ps1, or: pip install anvil-uplink")

    done = threading.Event()

    @anvil.server.callable("imageenhancer_run")
    def imageenhancer_run(job, picture):
        job = dict(job or {})
        with LOCK:
            STATE["busy"] = True
            t0 = time.time()
            log("Job %s: %s, %s MP, attempt %s" % (job.get("job_id"), job.get("style"), job.get("megapixels"), job.get("attempt")))
            try:
                data = picture.get_bytes()
                out, ctype, meta = STATE["engine"].process(data, job)
            except engines.EngineError as e:
                STATE["failed"] += 1
                log("Job %s failed: %s" % (job.get("job_id"), e))
                raise RuntimeError(str(e))
            except Exception as e:
                STATE["failed"] += 1
                log("Job %s crashed: %s" % (job.get("job_id"), traceback.format_exc()))
                raise RuntimeError("The worker crashed on this picture: %s: %s" % (type(e).__name__, e))
            finally:
                STATE["busy"] = False
            secs = time.time() - t0
            STATE["done"] += 1
            log("Job %s done in %.1f s (%dx%d)" % (job.get("job_id"), secs, meta.get("width", 0), meta.get("height", 0)))
            ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[ctype]
            reply = dict(STATE["engine"].info())
            reply.update(meta, image=anvil.BlobMedia(ctype, out, name="%s.%s" % (job.get("job_id") or "result", ext)), seconds=round(secs, 2))
            if args.once:
                threading.Timer(1.0, done.set).start()
            return reply

    @anvil.server.callable("imageenhancer_ping")
    def imageenhancer_ping():
        info = worker_info()
        info.update(busy=STATE["busy"], done=STATE["done"], failed=STATE["failed"],
                    up_minutes=int((time.time() - STATE["started"]) / 60))
        return info

    url = cfg.get("anvil_url") or None
    log("Connecting to Anvil%s ..." % (" at " + url if url else ""))
    try:
        if url:
            anvil.server.connect(cfg["uplink_key"], url=url)
        else:
            anvil.server.connect(cfg["uplink_key"])
    except Exception as e:
        if wrong_key(e):
            stop_wrong_key()
        log("Couldn't connect: %s" % e)
        log("Check the Uplink key (it must be the SERVER key) and the internet connection, then start again.")
        sys.exit(2)
    r = hello(anvil.server)
    if r:
        log("Connected. %s waiting in the queue. Close this window (or Ctrl+C) to stop." % r.get("waiting", 0))

    def heartbeat():
        while not done.is_set():
            done.wait(float(cfg.get("heartbeat_seconds", 120)))
            if not done.is_set():
                hello(anvil.server)
    threading.Thread(target=heartbeat, daemon=True).start()

    def bye():
        try:
            anvil.server.call("enhancer_worker_bye")
            log("Said bye to the app.")
        except Exception:
            pass
        proc = getattr(STATE["engine"], "proc", None)
        if proc is not None and proc.poll() is None:
            log("Stopping the ComfyUI this worker started.")
            proc.terminate()
    atexit.register(bye)

    try:
        while not done.is_set():
            done.wait(1.0)
    except KeyboardInterrupt:
        log("Stopping.")
    finally:
        done.set()


if __name__ == "__main__":
    main()
