"""Tests for the worker's engines against the fake ComfyUI (no GPU, no model needed).

    python worker/tests/test_worker.py      -> WORKER TESTS PASSED
"""
import io
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE]
from PIL import Image  # noqa: E402

import engines  # noqa: E402
from fake_comfy import FAKE, start_fake  # noqa: E402

logs = []
log = logs.append


def picture(w=640, h=480, mode="RGB"):
    im = Image.new(mode, (w, h), (40, 120, 200, 255) if mode == "RGBA" else (40, 120, 200))
    for x in range(0, w, 40):
        for y in range(h // 3, h // 2):
            im.putpixel((x, y), (250, 200, 30) if mode == "RGB" else (250, 200, 30, 0))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


srv, url = start_fake()
tmp = tempfile.mkdtemp()
cfg = {"comfy_url": url, "start_comfy": False, "comfy_dir": tmp, "steps": 4, "job_timeout": 30, "max_megapixels": 2.0}

# ---- ComfyUI: prepare
eng = engines.make(cfg, log)
assert isinstance(eng, engines.ComfyEngine)
assert eng.prepare() is True
assert "RTX 4070" in eng.info()["gpu"] and "8 GB" in eng.info()["gpu"], eng.info()
assert eng.info()["model"] == "flux-2-klein-4b-fp8"
print("ok   prepare: nodes, model files and GPU found")

# ---- one job, all options
job = {"job_id": "job_test1", "style": "kids_book", "instruction": "Repaint this image as a picture-book page. Keep the same subjects.",
       "megapixels": 0.5, "seed": 123, "format": "jpeg", "size": "source", "width": 640, "height": 480}
out, ctype, meta = eng.process(picture(), job)
im = Image.open(io.BytesIO(out))
assert ctype == "image/jpeg" and im.format == "JPEG" and im.size == (640, 480), (ctype, im.format, im.size)
assert meta["seed"] == 123 and meta["width"] == 640
p = FAKE["prompts"][-1]
by = {n["class_type"]: n["inputs"] for n in p.values()}
assert by["CLIPTextEncode"]["text"] == job["instruction"], "the instruction reaches the model"
assert by["RandomNoise"]["noise_seed"] == 123 and by["ImageScaleToTotalPixels"]["megapixels"] == 0.5
assert by["ImageScaleToTotalPixels"]["resolution_steps"] == 1, "new required inputs get their defaults"
assert by["Flux2Scheduler"]["steps"] == 4 and by["CFGGuider"]["cfg"] == 1.0
assert by["SaveImage"]["filename_prefix"] == "imageenhancer/job_test1"
assert by["LoadImage"]["image"] == "ie_job_test1.png" and "_meta" not in p["1"]
assert not any(v == "__PROMPT__" or v == "__INPUT__" for n in p.values() for v in n["inputs"].values())
print("ok   process: instruction, seed, megapixels, steps, size=source, jpeg")

# ---- model size, random seed, transparency flattened, png
out, ctype, meta = eng.process(picture(800, 600, "RGBA"), {"job_id": "job_test2", "instruction": "x", "megapixels": 1.0})
im = Image.open(io.BytesIO(out))
assert ctype == "image/png" and abs(im.size[0] * im.size[1] - 1e6) < 30000, im.size
assert isinstance(meta["seed"], int) and meta["seed"] > 0
assert FAKE["uploads"]["ie_job_test2.png"][:8] == b"\x89PNG\r\n\x1a\n"
assert Image.open(io.BytesIO(FAKE["uploads"]["ie_job_test2.png"])).mode == "RGB", "transparency is flattened before upload"
print("ok   process: ~1 MP by default, random seed, transparency flattened")

# ---- megapixels are capped by config
eng.process(picture(), {"job_id": "job_test3", "instruction": "x", "megapixels": 9})
assert [n for n in FAKE["prompts"][-1].values() if n["class_type"] == "ImageScaleToTotalPixels"][0]["inputs"]["megapixels"] == 2.0
print("ok   megapixels capped at max_megapixels")

# ---- errors become clear sentences
FAKE["mode"] = "error"
try:
    eng.process(picture(), {"job_id": "job_err", "instruction": "x"})
    raise AssertionError("expected an error")
except engines.EngineError as e:
    assert "out of memory" in str(e), e
FAKE["mode"] = "ok"
FAKE["models"] = False
try:
    engines.make(cfg, log).prepare()
    raise AssertionError("expected a missing-model error")
except engines.EngineError as e:
    assert "setup_comfyui.ps1" in str(e) and "flux-2-klein" in str(e), e
FAKE["models"] = True
try:
    engines.make(dict(cfg, comfy_url="http://127.0.0.1:9"), log).prepare()
    raise AssertionError("expected not running")
except engines.EngineError as e:
    assert "isn't running" in str(e) or "isn't installed" in str(e) or "start_comfy" in str(e), e
try:
    eng.process(b"not a picture at all", {"job_id": "job_bad", "instruction": "x"})
    raise AssertionError("expected a bad-picture error")
except engines.EngineError as e:
    assert "couldn't be opened" in str(e)
print("ok   errors: out of memory, missing model, ComfyUI not running, broken picture")

# ---- classic engine: every style, every format
classic = engines.make({"backend": "classic"}, log)
assert classic.prepare() and classic.info()["backend"] == "classic"
for style in ["kids_book", "scifi", "realistic", "anime", "watercolor", "oil_painting", "cartoon_3d", "comic", "fantasy", "claymation"]:
    for fmt, kind in (("png", "PNG"), ("webp", "WEBP")):
        out, ctype, meta = classic.process(picture(320, 240), {"style": style, "megapixels": 0.25, "format": fmt})
        assert Image.open(io.BytesIO(out)).format == kind, (style, fmt)
print("ok   classic engine: 10 styles x png/webp")

srv.shutdown()
print("WORKER TESTS PASSED")
