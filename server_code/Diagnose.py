"""The problem doctor: turns the PC's error sentences into a likely cause and what to do about it.

explain(error) -> {"key", "title", "steps": [..]} for any job error (None when there is no error).
problems(days) -> failed and retrying jobs of the last `days` days grouped by cause, for the Queue page's
"Needs attention" card and the Health page. Rules are plain lower-case phrases matched in order (first match wins);
the phrases come from worker/engines.py (EngineError sentences), Worker.py and the usual PyTorch / ROCm messages.
"""
import datetime as dt

from anvil.tables import app_tables
import anvil.tables.query as q

from . import common as C

RULES = [
    ("oom", ("out of memory", "outofmemory", "gpu memory", "vram", "allocation on device", "exceed allowed memory", "not enough memory",
             "cudamalloc", "hip error", "memory access fault"),
     "The graphics card ran out of memory",
     ["Send it again at less detail (0.5 or 0.75 MP): on the Test bench, or megapixels from the app.",
      "Close other programs that use the graphics card (games, video, other AI tools) and try again.",
      "Still failing? Add \"--lowvram\" (or \"--disable-dynamic-vram\") to comfy_args in worker/config.json, then restart the worker."]),
    ("model_missing", ("can't find the model",),
     "A model file is missing on the PC",
     ["Run the installer again (worker/setup_comfyui.ps1 on Windows, worker/install_ubuntu.sh on Ubuntu): it only downloads what's missing.",
      "Then restart the worker and press Try again."]),
    ("nodes", ("doesn't know the nodes",),
     "ComfyUI is too old for the workflow",
     ["Update ComfyUI by running the installer again, then restart the worker."]),
    ("comfy_down", ("isn't reachable", "isn't running", "stopped while starting", "didn't answer within",
                    "connection refused", "isn't installed"),
     "ComfyUI wasn't running on the PC",
     ["Restart the worker (start_worker.bat or start_worker.sh): it starts ComfyUI by itself.",
      "If ComfyUI stops while starting, read worker/comfyui.log on the PC: it usually names the problem (graphics driver, memory).",
      "Then press Ask the PC now on the Queue page."]),
    ("timeout", ("didn't finish within",),
     "The picture took too long",
     ["Big pictures take longer: send it again at 1 MP or less.",
      "If every picture times out, the graphics card may be overheating or busy with something else: check the PC.",
      "You can give each picture more time with job_timeout (seconds) in worker/config.json."]),
    ("rejected", ("rejected the workflow", "comfyui refused", "comfyui failed"),
     "ComfyUI refused the job",
     ["Read the end of worker/comfyui.log on the PC: it names the node that failed.",
      "If you edited worker/workflows/flux2_klein_edit.json, put the original back (git checkout on the PC)."]),
    ("interrupted", ("interrupted", "looked stuck"),
     "The job was interrupted",
     ["The PC, the worker or the app restarted while it was painting. Trying again usually works."]),
    ("picture", ("couldn't be opened", "without a png", "couldn't be read", "real png"),
     "The picture couldn't be read",
     ["Check the picture opens on your computer, save it again as PNG, and send it again.",
      "If only results fail this way, update the worker (git pull) and restart it."]),
    ("crash", ("crashed", "pillow isn't installed"),
     "The worker crashed on this picture",
     ["worker/worker.log on the PC has the full error.",
      "Update the worker (git pull in the image-enhancer folder), restart it and try again."]),
]
OTHER = ("other", "Something else went wrong",
         ["Read the error below and worker/worker.log on the PC.", "Press Try again once the PC looks healthy."])


def explain(error):
    if not error:
        return None
    low = str(error).lower()
    for key, phrases, title, steps in RULES:
        if any(p in low for p in phrases):
            return {"key": key, "title": title, "steps": list(steps)}
    return {"key": OTHER[0], "title": OTHER[1], "steps": list(OTHER[2])}


def keys():
    return [r[0] for r in RULES] + [OTHER[0]]


def problems(days=7):
    """Failed jobs of the last `days` days and jobs waiting for another try, grouped by cause (worst first)."""
    since = C.now() - dt.timedelta(days=days)
    rows = list(app_tables.jobs.search(status="failed", finished=q.greater_than(since)))
    rows += [j for j in app_tables.jobs.search(status="queued") if j["error"]]
    groups: dict = {}
    for j in rows:
        d = explain(j["error"] or "Failed without a message.")
        g = groups.setdefault(d["key"], dict(d, failed=0, retrying=0, retryable=0, demo=0, job_id=None, error="", _t=None))
        if j["status"] == "failed":
            g["failed"] += 1
            if j["is_demo"]:
                g["demo"] += 1
            else:
                g["retryable"] += 1
        else:
            g["retrying"] += 1
        t = j["finished"] or j["created"]
        if g["_t"] is None or (t and t > g["_t"]):
            g["_t"], g["job_id"], g["error"] = t, j["job_id"], C.text(j["error"], 240)
    out = sorted(groups.values(), key=lambda g: -(g["failed"] + g["retrying"]))
    for g in out:
        g.pop("_t", None)
    return out
