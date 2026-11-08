# Image Enhancer worker (runs on your PC)

Links your PC's graphics card to the Image Enhancer app. The app keeps the queue; this worker paints one picture at a
time with **FLUX.2 [klein] 4B** (Black Forest Labs, Apache 2.0, so fine for commercial apps) in **ComfyUI**, and
sends the result back through **Anvil Uplink**.

## Why this model

FLUX.2 [klein] 4B is an image-*editing* model: it takes your picture plus a plain instruction ("Repaint this image as
a warm children's picture-book illustration... Keep the same subjects, composition and poses") and redraws it while
keeping the layout. That is exactly "vector art in, styled art out". The distilled version needs only 4 steps, fits
an 8 GB card in fp8 (ComfyUI moves the text encoder to system RAM when needed), and its licence allows commercial
use (the 9B version doesn't). On an RTX 4070 Laptop (8 GB) expect roughly 20 to 60 s per 1-megapixel picture once
loaded; the first picture after starting takes longer while the model loads.

## Install (once)

Needs Windows 10/11, an NVIDIA card with 8 GB+, Python 3.10-3.13, Git, ~15 GB free disk.

1. Right-click `setup_comfyui.ps1` → **Run with PowerShell**
   (or `powershell -ExecutionPolicy Bypass -File setup_comfyui.ps1`). It:
   - clones ComfyUI into `worker\ComfyUI` with its own Python environment and PyTorch for CUDA 12.8;
   - downloads `flux-2-klein-4b-fp8.safetensors` (4.1 GB), `qwen_3_4b.safetensors` (8.0 GB, the text encoder) and
     `flux2-vae.safetensors` (0.3 GB) into ComfyUI's `models` folders (downloads resume if interrupted);
   - makes the worker's own environment (`worker\.venv`: anvil-uplink, Pillow);
   - runs `enhancer_worker.py --check` (starts ComfyUI once and checks it finds every node and model file).
   Run it again any time to update ComfyUI.
2. In the Anvil editor for the app: **+ Add feature → Uplink → Enable the Server Uplink**, copy the key (`server_...`).

## Run

Double-click `start_worker.bat`. The first time it asks for the Uplink key (saved in `worker\config.json`, which never
leaves this PC; it's in .gitignore). Then it starts ComfyUI in the background if it isn't running, connects and says
hello; the console's lamp turns green and any waiting pictures start straight away. Close the window to stop (the
worker tells the app, and stops the ComfyUI it started). To start it with Windows: Win+R → `shell:startup` → put a
shortcut to `start_worker.bat` there.

`start_worker.bat --backend classic` uses simple Pillow filters instead of the model (no GPU), to test the round trip.

## Settings (`config.json`, see `config.example.json`)

| Setting | Default | What it does |
|---|---|---|
| `uplink_key` | asked once | the app's SERVER Uplink key |
| `anvil_url` | empty | only for a self-hosted Anvil App Server: `ws://host:port/_/uplink` |
| `backend` | `comfyui` | or `classic` (test filters) |
| `comfy_url` | `http://127.0.0.1:8188` | use your own ComfyUI elsewhere |
| `comfy_dir` | `ComfyUI` | where ComfyUI is installed (to start it and tidy its files) |
| `start_comfy` | `true` | start ComfyUI when it isn't running |
| `comfy_args` | `[]` | extra ComfyUI flags, e.g. `["--lowvram"]` on a 6 GB card |
| `steps` | `4` | sampling steps (the distilled model is made for 4) |
| `max_megapixels` | `2.0` | cap on what apps may ask for |
| `job_timeout` | `900` | seconds before a stuck picture is stopped (the app retries it later) |
| `heartbeat_seconds` | `120` | how often it tells the app it's still there |
| `tidy_files` | `true` | delete each job's files from ComfyUI's input/output folders |

## Changing the look

- The words for each style live in the app (console → Styles): change them there, no restart needed.
- The ComfyUI graph is `workflows/flux2_klein_edit.json` (API format). To use another workflow, export it from ComfyUI
  with **Save (API)**, put `__PROMPT__` in the text field and `__INPUT__` in the LoadImage field, and set `workflow`
  in config.json. The worker fills the seed, megapixels, steps and output name, and any new required inputs a ComfyUI
  update adds.
- Bigger card (16 GB+)? Leave it as is; it simply runs faster. The 9B model is non-commercial, so it isn't used.

## Files

`enhancer_worker.py` (Uplink, hello/bye, one-at-a-time lock), `engines.py` (ComfyUI + classic), `workflows/`,
`setup_comfyui.ps1`, `start_worker.bat`, `requirements.txt`, `tests/` (`fake_comfy.py` + `test_worker.py`: run
`python worker/tests/test_worker.py`). Logs: `worker.log`, `comfyui.log`.
