"""Demo content, so the console never looks empty on day one: a sample app key (switched off, so it can't be used)
and a few finished example jobs with small generated pictures. Demo jobs are never sent to the PC and never count
towards time estimates. Loaded automatically the first time the console opens, removed or reloaded from
Admin -> Demo data. Removing it is remembered: it doesn't come back.
"""
import datetime as dt
import math
import secrets

import anvil
from anvil.tables import app_tables

from . import common as C
from . import Pictures, Styles

DEMO_APP = "Sample app (demo)"
# style, status, minutes ago, seconds taken, error
DEMO_JOBS = [
    ("kids_book", "done", 38, 41.2, None),
    ("scifi", "done", 31, 37.9, None),
    ("watercolor", "done", 22, 44.6, None),
    ("realistic", "failed", 15, None, "The PC couldn't make this picture: ComfyUI ran out of GPU memory (try megapixels 0.75)."),
]
DEMO_TABLES = ["jobs", "events", "clients"]   # children before parents

TINTS = {"kids_book": (1.05, 0.98, 0.86), "scifi": (0.70, 0.95, 1.25), "watercolor": (1.0, 1.02, 1.08), "realistic": (0.95, 0.95, 0.95)}


def _scene(w, h, style=None):
    """A flat 'vector' scene (sky, sun, hills, a little house); with a style, a textured, tinted take on it."""
    tint = TINTS.get(style or "", (1, 1, 1))

    def px(x, y):
        hill = h * 0.62 + math.sin(x / w * 5.2) * h * 0.07
        if (x - w * 0.74) ** 2 + (y - h * 0.26) ** 2 < (h * 0.12) ** 2:
            c = (244, 196, 72)
        elif w * 0.22 < x < w * 0.40 and h * 0.48 < y < hill + 2:
            c = (226, 83, 58) if y < h * 0.56 else (240, 234, 222)
        elif y > hill:
            c = (79, 141, 92) if y < h * 0.85 else (58, 112, 74)
        else:
            c = (128, 186, 228)
        if style:
            n = ((x * 73856093) ^ (y * 19349663) ^ 0x5bd1e995) % 23 - 11
            c = tuple(max(0, min(255, int(v * t + n + (8 if style == "kids_book" else 0)))) for v, t in zip(c, tint))
        return c
    return px


def state():
    return C.get_setting("demo", "never")  # "never" | "loaded" | "removed"


def ensure_loaded():
    if state() == "never":
        load()


def load():
    remove(remember=False)
    Styles.ensure()
    client = app_tables.clients.add_row(name=DEMO_APP, key_prefix="ie_demo00", key_hash="demo-" + secrets.token_hex(16),
                                        webhook_secret="", active=False, hourly_limit=60,
                                        note="An example key. It is switched off, so it can't be used.",
                                        created=C.now() - dt.timedelta(days=3), jobs_total=len(DEMO_JOBS), is_demo=True)
    src = Pictures.png(160, 120, _scene(160, 120))
    for i, (style, status, ago, secs, err) in enumerate(DEMO_JOBS):
        made = C.now() - dt.timedelta(minutes=ago)
        st = Styles.get(style)
        res = Pictures.png(160, 120, _scene(160, 120, style)) if status == "done" else None
        job_id = "job_demo%04d" % (i + 1)
        app_tables.jobs.add_row(
            job_id=job_id, client=client, origin="api", style=style, prompt="",
            options={"fidelity": "balanced", "megapixels": 1.0, "format": "png", "size": "model", "extra": "",
                     "instruction": Styles.instruction(st, "balanced") if st else ""},
            source=anvil.BlobMedia("image/png", src, name="meadow-house.png"), source_key="demo" + secrets.token_hex(12),
            source_name="meadow-house.png", width=160, height=120,
            result=anvil.BlobMedia("image/png", res, name="meadow-house-%s.png" % style) if res else None,
            result_key=("demo" + secrets.token_hex(12)) if res else None, status=status, priority=0, created=made,
            started=made + dt.timedelta(seconds=3), finished=made + dt.timedelta(seconds=(secs or 30) + 3),
            attempts=1 if status == "done" else 3, seconds=secs, error=err,
            worker_info={"backend": "comfyui", "model": "flux-2-klein-4b-fp8", "seed": 1000 + i, "width": 160, "height": 120} if res else {},
            client_ref="demo-%d" % (i + 1), is_demo=True)
        app_tables.events.add_row(time=made, kind="done" if status == "done" else "failed",
                                  text=("Finished %s in %d s" % (job_id, secs)) if secs else ("Gave up on %s after 3 tries" % job_id),
                                  job_id=job_id, is_demo=True)
    C.set_setting("demo", "loaded")
    return counts()


def remove(remember=True):
    for name in DEMO_TABLES:
        for r in getattr(app_tables, name).search(is_demo=True):
            r.delete()
    for u in app_tables.users.search(is_demo=True):
        u.delete()
    if remember:
        C.set_setting("demo", "removed")
    return counts()


def counts():
    out = {}
    for name in DEMO_TABLES:
        out[name] = len(getattr(app_tables, name).search(is_demo=True))
    return out
