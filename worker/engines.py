"""The engines that actually repaint a picture on this PC.

    ComfyEngine    ComfyUI (local web API) running FLUX.2 [klein] 4B with workflows/flux2_klein_edit.json.
                   Starts ComfyUI itself if it isn't running (config: comfy_dir, start_comfy).
    ClassicEngine  Pillow filters only, no GPU, no model: a stand-in to test the whole round trip.

Both take (picture bytes, job dict from the app) and return (bytes, content type, info dict).
Every problem is raised as EngineError with a sentence the console shows to the owner.
Only the standard library and Pillow are used, so nothing here fights with ComfyUI's own packages.
"""
import copy
import io
import json
import os
import random
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
FORMATS = {"png": ("PNG", "image/png"), "jpeg": ("JPEG", "image/jpeg"), "webp": ("WEBP", "image/webp")}


class EngineError(Exception):
    pass


def _pil():
    try:
        from PIL import Image  # noqa: F401
        import PIL
        return PIL
    except ImportError:
        raise EngineError("Pillow isn't installed for the worker: run setup_comfyui.ps1 again (or pip install pillow).")


def open_rgb(data):
    """Any picture -> an RGB Pillow image (transparency flattened onto white, as vector art expects)."""
    _pil()
    from PIL import Image, ImageOps
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:
        raise EngineError("The picture couldn't be opened (is it a real PNG, JPEG or WebP?).")
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        im = bg
    return im.convert("RGB")


def finish(im, job):
    """Resize back to the sent picture's size if asked (size=source) and encode in the asked format."""
    from PIL import Image
    if job.get("size") == "source" and job.get("width") and job.get("height"):
        im = im.resize((int(job["width"]), int(job["height"])), Image.LANCZOS)
    fmt = FORMATS.get(job.get("format") or "png", FORMATS["png"])
    out = io.BytesIO()
    if fmt[0] == "JPEG":
        im.convert("RGB").save(out, "JPEG", quality=92, optimize=True)
    elif fmt[0] == "WEBP":
        im.save(out, "WEBP", quality=90, method=5)
    else:
        im.save(out, "PNG", optimize=False)
    return out.getvalue(), fmt[1], im.size


# =============================================================================================== ComfyUI
class ComfyEngine(object):
    name = "comfyui"

    def __init__(self, cfg, log):
        self.cfg, self.log = cfg, log
        self.url = (cfg.get("comfy_url") or "http://127.0.0.1:8188").rstrip("/")
        path = cfg.get("workflow") or "workflows/flux2_klein_edit.json"
        self.workflow_path = path if os.path.isabs(path) else os.path.join(HERE, path)
        with open(self.workflow_path, encoding="utf-8") as f:
            self.workflow = json.load(f)
        self.comfy_dir = cfg.get("comfy_dir") or "ComfyUI"
        if not os.path.isabs(self.comfy_dir):
            self.comfy_dir = os.path.join(HERE, self.comfy_dir)
        self.proc = None
        self.object_info = {}
        self.gpu = ""
        self.model = "FLUX.2 klein 4B"

    # ---- talking to ComfyUI
    def _req(self, path, data=None, headers=None, timeout=30, raw=False):
        req = urllib.request.Request(self.url + path, data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            raise EngineError("ComfyUI refused %s (HTTP %s): %s" % (path.split("?")[0], e.code, _comfy_error(detail)))
        except (urllib.error.URLError, OSError) as e:
            raise EngineError("ComfyUI isn't reachable at %s (%s)." % (self.url, getattr(e, "reason", e)))
        return body if raw else json.loads(body.decode("utf-8") or "null")

    def alive(self):
        try:
            stats = self._req("/system_stats", timeout=4)
        except EngineError:
            return False
        devs = (stats or {}).get("devices") or []
        if devs:
            d = devs[0]
            self.gpu = (d.get("name") or "").split(" : ")[0].replace("cuda:0 ", "").strip()
            vram = d.get("vram_total")
            if vram:
                self.gpu += " (%d GB)" % round(vram / 1073741824.0)
        return True

    def start(self):
        """Start ComfyUI from comfy_dir (installed by setup_comfyui.ps1) and wait until it answers."""
        main = os.path.join(self.comfy_dir, "main.py")
        if not os.path.exists(main):
            raise EngineError("ComfyUI isn't running at %s and isn't installed in %s. Run setup_comfyui.ps1 first, "
                              "or start your own ComfyUI and set comfy_url in config.json." % (self.url, self.comfy_dir))
        py = os.path.join(self.comfy_dir, "venv", "Scripts", "python.exe")
        if not os.path.exists(py):
            py = os.path.join(self.comfy_dir, "venv", "bin", "python")
        if not os.path.exists(py):
            py = sys.executable
        port = urllib.parse.urlparse(self.url).port or 8188
        args = [py, main, "--listen", "127.0.0.1", "--port", str(port), "--disable-auto-launch"] + list(self.cfg.get("comfy_args") or [])
        self.log("Starting ComfyUI: %s" % " ".join(args[1:]))
        logf = open(os.path.join(HERE, "comfyui.log"), "ab")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if self.cfg.get("hide_comfy_window", True) else 0
        self.proc = subprocess.Popen(args, cwd=self.comfy_dir, stdout=logf, stderr=subprocess.STDOUT, creationflags=flags)
        end = time.time() + float(self.cfg.get("comfy_start_timeout", 240))
        while time.time() < end:
            if self.proc.poll() is not None:
                raise EngineError("ComfyUI stopped while starting (exit code %s). See worker/comfyui.log." % self.proc.returncode)
            if self.alive():
                self.log("ComfyUI is up.")
                return
            time.sleep(2)
        raise EngineError("ComfyUI didn't answer within %ss of starting. See worker/comfyui.log." % self.cfg.get("comfy_start_timeout", 240))

    def ensure_running(self):
        if self.alive():
            return
        if not self.cfg.get("start_comfy", True):
            raise EngineError("ComfyUI isn't running at %s (start_comfy is off in config.json)." % self.url)
        self.start()

    def prepare(self):
        """Check ComfyUI runs, knows every node in the workflow, and has the model files."""
        self.ensure_running()
        self.object_info = self._req("/object_info", timeout=60) or {}
        missing = sorted({n["class_type"] for n in self.workflow.values() if n["class_type"] not in self.object_info})
        if missing:
            raise EngineError("This ComfyUI doesn't know the nodes %s. Update ComfyUI (run setup_comfyui.ps1 again)." % ", ".join(missing))
        problems = []
        for node in self.workflow.values():
            for field in ("unet_name", "clip_name", "vae_name"):
                want = node["inputs"].get(field)
                if not isinstance(want, str):
                    continue
                options = _choices(self.object_info, node["class_type"], field)
                if options is not None and want not in options:
                    problems.append(want)
        if problems:
            raise EngineError("ComfyUI can't find the model file(s) %s. Run setup_comfyui.ps1 to download them." % ", ".join(problems))
        unet = [n["inputs"].get("unet_name") for n in self.workflow.values() if n["class_type"] == "UNETLoader"]
        if unet and unet[0]:
            self.model = unet[0].replace(".safetensors", "")
        return True

    def info(self):
        return {"backend": "comfyui", "model": self.model, "gpu": self.gpu}

    # ---- one job
    def build(self, job, image_name, seed):
        wf = copy.deepcopy(self.workflow)
        mp = min(float(self.cfg.get("max_megapixels", 2.0)), max(0.25, float(job.get("megapixels") or 1.0)))
        steps = int(self.cfg.get("steps") or 0)
        for node in wf.values():
            node.pop("_meta", None)
            inp = node["inputs"]
            for k, v in list(inp.items()):
                if v == "__PROMPT__":
                    inp[k] = job.get("instruction") or "Repaint this image."
                elif v == "__INPUT__":
                    inp[k] = image_name
            if "noise_seed" in inp and not isinstance(inp["noise_seed"], list):
                inp["noise_seed"] = seed
            if "seed" in inp and not isinstance(inp["seed"], list):
                inp["seed"] = seed
            if node["class_type"] == "ImageScaleToTotalPixels":
                inp["megapixels"] = mp
            if steps and "steps" in inp and not isinstance(inp["steps"], list):
                inp["steps"] = steps
            if node["class_type"] == "SaveImage":
                inp["filename_prefix"] = "imageenhancer/%s" % (job.get("job_id") or "out")
            # newer ComfyUI versions add required inputs (e.g. resolution_steps): fill them with their defaults
            for k, default in _required_defaults(self.object_info, node["class_type"]).items():
                if k not in inp:
                    inp[k] = default
        return wf

    def upload(self, png_bytes, name):
        boundary = "----ie" + uuid.uuid4().hex
        parts = []
        for field, value in (("overwrite", "true"), ("type", "input")):
            parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, field, value)).encode())
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"image\"; filename=\"%s\"\r\nContent-Type: image/png\r\n\r\n"
                      % (boundary, name)).encode() + png_bytes + b"\r\n")
        parts.append(("--%s--\r\n" % boundary).encode())
        r = self._req("/upload/image", data=b"".join(parts), headers={"Content-Type": "multipart/form-data; boundary=" + boundary}, timeout=60)
        sub = r.get("subfolder") or ""
        return (sub + "/" if sub else "") + r["name"]

    def process(self, data, job):
        self.ensure_running()
        if not self.object_info:
            self.prepare()
        im = open_rgb(data)
        buf = io.BytesIO()
        im.save(buf, "PNG")
        name = self.upload(buf.getvalue(), "ie_%s.png" % (job.get("job_id") or uuid.uuid4().hex[:8]))
        seed = job.get("seed")
        seed = int(seed) if seed is not None else random.randint(1, 2 ** 48)
        wf = self.build(job, name, seed)
        reply = self._req("/prompt", data=json.dumps({"prompt": wf, "client_id": "imageenhancer"}).encode("utf-8"),
                          headers={"Content-Type": "application/json"}, timeout=60)
        if reply.get("node_errors"):
            raise EngineError("ComfyUI rejected the workflow: %s" % _comfy_error(json.dumps(reply)))
        pid = reply["prompt_id"]
        end = time.time() + float(self.cfg.get("job_timeout", 900))
        out = None
        while time.time() < end:
            hist = self._req("/history/" + pid, timeout=30)
            entry = (hist or {}).get(pid)
            if entry:
                st = entry.get("status") or {}
                if st.get("status_str") == "error":
                    raise EngineError("ComfyUI failed: %s" % _history_error(st))
                for node_out in (entry.get("outputs") or {}).values():
                    imgs = node_out.get("images") or []
                    if imgs:
                        out = imgs[0]
                        break
                if out or st.get("completed"):
                    break
            time.sleep(1.0)
        if out is None:
            try:
                self._req("/interrupt", data=b"{}", headers={"Content-Type": "application/json"})
            except EngineError:
                pass
            raise EngineError("ComfyUI didn't finish within %ss (stopped it)." % self.cfg.get("job_timeout", 900))
        q = urllib.parse.urlencode({"filename": out["filename"], "subfolder": out.get("subfolder", ""), "type": out.get("type", "output")})
        png = self._req("/view?" + q, raw=True, timeout=60)
        self._tidy(name, out)
        result, ctype, size = finish(open_rgb(png), job)
        return result, ctype, {"seed": seed, "steps": int(self.cfg.get("steps") or 4), "width": size[0], "height": size[1]}

    def _tidy(self, input_name, out):
        """Delete this job's files from ComfyUI's input/output folders (the app keeps the pictures)."""
        if not self.cfg.get("tidy_files", True):
            return
        for path in (os.path.join(self.comfy_dir, "input", input_name),
                     os.path.join(self.comfy_dir, out.get("type", "output"), out.get("subfolder", ""), out["filename"])):
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except OSError:
                pass


def _choices(info, cls, field):
    spec = (info.get(cls) or {}).get("input") or {}
    for group in ("required", "optional"):
        v = (spec.get(group) or {}).get(field)
        if v and isinstance(v[0], list):
            return v[0]
        if v and v[0] == "COMBO" and len(v) > 1 and isinstance(v[1], dict):
            return v[1].get("options")
    return None


def _required_defaults(info, cls):
    out = {}
    for field, v in (((info.get(cls) or {}).get("input") or {}).get("required") or {}).items():
        if not v:
            continue
        kind, opts = v[0], (v[1] if len(v) > 1 and isinstance(v[1], dict) else {})
        if "default" in opts:
            out[field] = opts["default"]
        elif isinstance(kind, list) and kind:
            out[field] = kind[0]
    return out


def _comfy_error(text):
    try:
        d = json.loads(text)
    except ValueError:
        return text[:300]
    msgs = []
    err = d.get("error")
    if isinstance(err, dict):
        msgs.append(err.get("message", ""))
    for node in (d.get("node_errors") or {}).values():
        for e in node.get("errors") or []:
            msgs.append("%s (%s)" % (e.get("message", ""), e.get("details", "")))
    return "; ".join(m for m in msgs if m)[:400] or text[:300]


def _history_error(status):
    for kind, data in status.get("messages") or []:
        if kind == "execution_error" and isinstance(data, dict):
            return ("%s: %s" % (data.get("exception_type", ""), data.get("exception_message", ""))).strip()[:400]
    return "unknown error"


# =============================================================================================== classic (test)
class ClassicEngine(object):
    """No model, no GPU: quick Pillow looks per style, to test the queue end to end. Not AI."""
    name = "classic"

    def __init__(self, cfg, log):
        self.cfg, self.log = cfg, log

    def prepare(self):
        _pil()
        return True

    def info(self):
        return {"backend": "classic", "model": "Pillow filters (test engine, not AI)", "gpu": "none"}

    def process(self, data, job):
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps
        t0 = time.time()
        im = open_rgb(data)
        mp = max(0.25, min(2.0, float(job.get("megapixels") or 1.0)))
        k = (mp * 1e6 / float(im.size[0] * im.size[1])) ** 0.5
        im = im.resize((max(16, int(im.size[0] * k)), max(16, int(im.size[1] * k))), Image.LANCZOS)
        style = job.get("style") or ""
        rnd = random.Random(job.get("seed") or 7)

        def tint(img, rgb, amount):
            return Image.blend(img, Image.new("RGB", img.size, rgb), amount)

        def edges(img, strength=1.0):
            e = ImageOps.invert(img.convert("L").filter(ImageFilter.FIND_EDGES)).point(lambda v: 255 if v > 200 else int(v * strength))
            return Image.composite(img, Image.new("RGB", img.size, (30, 24, 20)), e)

        def grain(img, amount=10):
            noise = Image.effect_noise(img.size, amount * 3).convert("RGB")
            return Image.blend(img, noise, 0.06)

        if style == "kids_book":
            im = grain(tint(im.filter(ImageFilter.ModeFilter(5)).filter(ImageFilter.SMOOTH_MORE), (255, 236, 200), .12))
        elif style == "scifi":
            im = ImageEnhance.Contrast(tint(im, (20, 120, 160), .22)).enhance(1.35)
            im = Image.blend(im, im.filter(ImageFilter.GaussianBlur(8)), .25)
        elif style == "realistic":
            im = ImageEnhance.Color(im.filter(ImageFilter.GaussianBlur(1.2)).filter(ImageFilter.UnsharpMask(3, 120, 2)) ).enhance(.85)
        elif style == "anime":
            im = edges(ImageOps.posterize(ImageEnhance.Color(im).enhance(1.3), 4))
        elif style == "watercolor":
            im = grain(ImageEnhance.Brightness(im.filter(ImageFilter.MedianFilter(7)).filter(ImageFilter.GaussianBlur(1.5))).enhance(1.08), 6)
        elif style == "oil_painting":
            im = ImageEnhance.Contrast(im.filter(ImageFilter.ModeFilter(9))).enhance(1.15)
        elif style == "cartoon_3d":
            im = ImageEnhance.Color(im.filter(ImageFilter.SMOOTH_MORE).filter(ImageFilter.SMOOTH_MORE)).enhance(1.4)
        elif style == "comic":
            im = edges(ImageOps.posterize(im, 3), 1.2)
        elif style == "fantasy":
            im = ImageEnhance.Color(tint(im, (255, 200, 120), .15)).enhance(1.3)
            im = Image.blend(im, im.filter(ImageFilter.GaussianBlur(10)), .2)
        elif style == "claymation":
            im = ImageEnhance.Contrast(im.filter(ImageFilter.ModeFilter(7)).filter(ImageFilter.SMOOTH_MORE)).enhance(1.25)
        else:
            im = ImageOps.autocontrast(im)
        time.sleep(float(self.cfg.get("classic_delay", 0)) + rnd.random() * 0.01)
        result, ctype, size = finish(im, job)
        return result, ctype, {"seed": job.get("seed") or 7, "width": size[0], "height": size[1], "seconds": time.time() - t0}


def make(cfg, log):
    kind = (cfg.get("backend") or "comfyui").lower()
    if kind == "classic":
        return ClassicEngine(cfg, log)
    if kind == "comfyui":
        return ComfyEngine(cfg, log)
    raise EngineError("Unknown backend %r in config.json (use comfyui or classic)." % kind)
