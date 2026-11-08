"""A tiny stand-in for ComfyUI's web API, for testing the worker without a GPU or the model.

    python fake_comfy.py [port]        (or start_fake(port) from a test)

Speaks the endpoints the worker uses: /system_stats, /object_info, /upload/image, /prompt, /history/<id>, /view,
/interrupt. A "render" checks the workflow's links, then returns the uploaded picture colour-inverted and scaled to
the requested megapixels. FAKE["mode"] = "error" makes the next renders fail like a real out-of-memory error.
"""
import io
import json
import re
import sys
import threading
import time
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image, ImageOps

FAKE = {"mode": "ok", "uploads": {}, "outputs": {}, "history": {}, "prompts": [], "models": True}

NODES = ["UNETLoader", "CLIPLoader", "VAELoader", "LoadImage", "ImageScaleToTotalPixels", "GetImageSize", "CLIPTextEncode",
         "ConditioningZeroOut", "VAEEncode", "ReferenceLatent", "CFGGuider", "RandomNoise", "KSamplerSelect", "Flux2Scheduler",
         "EmptyFlux2LatentImage", "SamplerCustomAdvanced", "VAEDecode", "SaveImage"]


def object_info():
    info = {n: {"input": {"required": {}}} for n in NODES}
    unet = ["flux-2-klein-4b-fp8.safetensors"] if FAKE["models"] else ["something-else.safetensors"]
    info["UNETLoader"]["input"]["required"] = {"unet_name": [unet], "weight_dtype": [["default", "fp8_e4m3fn"]]}
    info["CLIPLoader"]["input"]["required"] = {"clip_name": [["qwen_3_4b.safetensors"]], "type": [["flux2", "qwen_image"]],
                                               "device": [["default", "cpu"], {"default": "default"}]}
    info["VAELoader"]["input"]["required"] = {"vae_name": [["flux2-vae.safetensors"]]}
    # a newer ComfyUI input the workflow doesn't set: the worker must fill its default
    info["ImageScaleToTotalPixels"]["input"]["required"] = {"image": ["IMAGE"], "upscale_method": [["nearest-exact", "lanczos"]],
                                                            "megapixels": ["FLOAT", {"default": 1.0}],
                                                            "resolution_steps": ["INT", {"default": 1, "min": 1}]}
    return info


def render(prompt):
    for nid, node in prompt.items():
        for k, v in node["inputs"].items():
            if isinstance(v, list):
                assert len(v) == 2 and str(v[0]) in prompt, "node %s input %s links to a missing node" % (nid, k)
    req = object_info()["ImageScaleToTotalPixels"]["input"]["required"]
    scale = [n for n in prompt.values() if n["class_type"] == "ImageScaleToTotalPixels"][0]["inputs"]
    assert all(k in scale for k in req), "required inputs missing: %s" % [k for k in req if k not in scale]
    load = [n for n in prompt.values() if n["class_type"] == "LoadImage"][0]["inputs"]["image"]
    im = Image.open(io.BytesIO(FAKE["uploads"][load])).convert("RGB")
    mp = float(scale["megapixels"])
    k = (mp * 1e6 / (im.size[0] * im.size[1])) ** 0.5
    im = ImageOps.invert(im.resize((max(16, int(im.size[0] * k)), max(16, int(im.size[1] * k)))))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/system_stats":
            return self._json({"system": {"comfyui_version": "fake"}, "devices": [
                {"name": "cuda:0 NVIDIA GeForce RTX 4070 Laptop GPU : cudaMallocAsync", "vram_total": 8585216000}]})
        if u.path == "/object_info":
            return self._json(object_info())
        m = re.match(r"^/history/(.+)$", u.path)
        if m:
            h = FAKE["history"].get(m.group(1))
            if h and time.time() >= h["ready_at"]:
                return self._json({m.group(1): h["entry"]})
            return self._json({})
        if u.path == "/view":
            q = urllib.parse.parse_qs(u.query)
            data = FAKE["outputs"].get(q["filename"][0])
            if data is None:
                return self._json({"error": "not found"}, 404)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._json({"error": "unknown"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        if self.path == "/upload/image":
            m = re.search(rb'name="image"; filename="([^"]+)"\r\nContent-Type: [^\r]+\r\n\r\n', body)
            start = m.end()
            end = body.index(b"\r\n--", start)
            FAKE["uploads"][m.group(1).decode()] = body[start:end]
            return self._json({"name": m.group(1).decode(), "subfolder": "", "type": "input"})
        if self.path == "/prompt":
            prompt = json.loads(body)["prompt"]
            FAKE["prompts"].append(prompt)
            pid = uuid.uuid4().hex
            if FAKE["mode"] == "error":
                entry = {"status": {"status_str": "error", "completed": False, "messages": [
                    ["execution_error", {"exception_type": "torch.OutOfMemoryError", "exception_message": "CUDA out of memory"}]]},
                    "outputs": {}}
            else:
                try:
                    png = render(prompt)
                except AssertionError as e:
                    return self._json({"error": {"message": str(e)}, "node_errors": {"x": {"errors": [{"message": str(e)}]}}}, 400)
                name = "out_%s.png" % pid[:6]
                FAKE["outputs"][name] = png
                entry = {"status": {"status_str": "success", "completed": True, "messages": []},
                         "outputs": {"19": {"images": [{"filename": name, "subfolder": "imageenhancer", "type": "output"}]}}}
            FAKE["history"][pid] = {"ready_at": time.time() + 0.6, "entry": entry}
            return self._json({"prompt_id": pid, "number": len(FAKE["prompts"]), "node_errors": {}})
        if self.path == "/interrupt":
            return self._json({})
        self._json({"error": "unknown"}, 404)


def start_fake(port=0):
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1]


if __name__ == "__main__":
    srv, url = start_fake(int(sys.argv[1]) if len(sys.argv) > 1 else 8189)
    print("fake ComfyUI on", url, flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
