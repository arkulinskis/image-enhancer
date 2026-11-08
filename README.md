# Image Enhancer

A private image-restyling service for Arkvital's own apps. An app sends a picture (typically flat vector art) with a
style; the picture waits in a queue; the owner's PC repaints it with an open image model (FLUX.2 [klein] 4B in
ComfyUI) and the result goes back to the app through an HTTP API, with a position and an estimated finish time all
along. There is no public website: just an owner-only console and the API. Built on [Anvil](https://anvil.works) as
native Anvil Forms; the PC side is a small Python worker that connects through **Anvil Uplink**.

- **App repo:** github.com/arkulinskis/image-enhancer (branch `master`). Anvil pulls `master`.
- **Live:** not published yet (update `API` in `clients/enhancer_client.py` once it is).

```
your app --POST /v1/jobs--> Image Enhancer (Anvil: queue, keys, API) --Uplink--> PC worker --> ComfyUI + FLUX.2 [klein] 4B
your app <--result / webhook--                                       <--picture--
```

## What it does

**The queue (strictly one picture at a time, oldest first)**
- Pictures wait in order; the owner can move one to the front ("Do next"), cancel, retry or delete.
- A background dispatcher (`enhancer_dispatch`) hands the next picture to the PC over Uplink and saves the result.
- **PC away** (switched off, worker closed): the picture goes back to the front and the app **asks again in 15
  minutes** (setting), or **at once when the worker says hello** on reconnecting. Pictures are never lost.
- **PC error** (e.g. out of GPU memory): that picture waits 15 minutes and is tried again, up to 3 tries, then failed.
- **Estimated finish time** for every waiting picture and for "a picture sent now": the average time of recent jobs
  (per style once there are 3), plus the job on the PC, every job ahead and the next "ask again" time.
- A scheduled task (`enhancer_tick`, every 15 minutes) restarts the dispatcher if needed, puts interrupted jobs back,
  deletes finished jobs after 30 days (setting) and trims the activity log. Pause / resume the whole queue.

**The API (`/_/api/v1`, one key per app, `Authorization: Bearer ie_...`)**
- `POST /jobs` (JSON with base64 / data URL / `image_url`, raw `image/png` bytes, or multipart), `GET /jobs/<id>`
  (status, position, `eta_seconds`, `eta_at`, `next_try_at`, `result_url`; `?wait=20` long-polls), `GET /jobs/<id>/result`,
  `POST /jobs/<id>/cancel` (or `DELETE`), `GET /jobs`, `GET /queue`, `GET /styles`, `GET /health`, and
  `GET /files/<key>` (unguessable result/source links that work in an `<img>` without a key).
- Options: `style`, `prompt` (extra words), `fidelity` (loose / balanced / strict), `megapixels` (0.25-2), `size`
  (`model` or `source`), `format` (png / jpeg / webp), `seed`, `ref` (the app's own id), `callback_url` (https).
- Webhooks: `{"event": "job.done" | "job.failed", "job": {...}}` signed `X-Enhancer-Signature: sha256=<HMAC>` with the
  key's webhook secret. Limits: 15 MB, 64-8000 px, PNG/JPEG/WebP (SVG: export as PNG first), hourly limit per key.
- `clients/enhancer_client.py`: drop-in server module for the other Anvil apps (submit, status, wait, result, cancel,
  queue, styles, verified_webhook).

**Ten styles** (keys apps send): `kids_book`, `scifi`, `realistic`, `anime`, `watercolor`, `oil_painting`, `cartoon_3d`,
`comic`, `fantasy`, `claymation`. Each is an editable instruction (table `styles`); fidelity adds a "what to keep" sentence.

**The console (owner only; other accounts see "this console is private")**
- **Queue** `#home`: the PC lamp (ready / painting / not answering / offline / paused) with GPU and model, Ask the PC
  now, Check the PC, Pause; waiting list with positions and estimates; recent before/after; activity. Refreshes every 8 s.
- **Job** `#job/<id>`: before/after slider, every detail, the exact instruction the model got, download, retry, cancel, delete.
- **Test bench** `#try`: upload a picture (SVG is rasterised in the browser), pick a style + fidelity + options, send
  it through the real queue, watch it finish.
- **Apps & keys** `#keys`: one key per app, shown once with its webhook secret; edit, switch off, replace, delete.
- **Styles** `#styles`: rename, describe, rewrite instructions, switch on/off, reset to the original words.
- **Connect** `#setup`: PC setup steps, the API reference with this app's real address in the code samples, settings
  (retry minutes, tries per picture, days to keep).
- Admin (users, demo data), Profile, Privacy & Terms, Prepsto feedback.

**The PC worker (`worker/`)**
- `setup_comfyui.ps1`: installs ComfyUI (own venv, PyTorch CUDA 12.8), downloads FLUX.2 [klein] 4B fp8 (4.1 GB),
  the Qwen3 4B text encoder (8.0 GB) and the FLUX.2 VAE (0.3 GB), makes the worker's venv, runs a check.
- `start_worker.bat`: asks for the SERVER Uplink key once (saved in `worker/config.json`, git-ignored), starts ComfyUI
  if needed, connects, says hello every 2 minutes, paints one picture at a time, says bye on exit.
- `engines.py`: ComfyEngine (uploads the picture, fills `workflows/flux2_klein_edit.json`, polls, downloads, resizes /
  re-encodes, tidies ComfyUI's folders) and ClassicEngine (Pillow filters to test without a GPU: `--backend classic`).
- See `worker/README.md`.

## Setting it up

**Anvil (once):** Create app → Clone from GitHub `https://github.com/arkulinskis/image-enhancer`; check the Users
service; accept the Schema Mismatch ("The schema of the source code is correct"); sign up with arkulinskis@gmail.com
first (that account is the owner), then switch off sign-up in the Users service; add **Uplink → Enable the Server
Uplink** and copy the key; check **Scheduled Tasks** lists `enhancer_tick` every 15 minutes (paid plans; without it the
dispatcher still waits and retries by itself); Publish.

**PC:** `worker\setup_comfyui.ps1`, then `worker\start_worker.bat` and paste the server Uplink key.

**Each app:** make a key on Apps & keys, store it in that app's Secrets as `image_enhancer_key`, copy
`clients/enhancer_client.py` into its server code.

<!-- libraries:start -->
## Libraries and outside services

What this project uses besides its own code. Generated by `APP_MAKER/tools/libraries.py`; to change it, edit `APP_MAKER/libraries/catalog.py` and re-run the script.

| Name | How it gets in | Used here for |
|---|---|---|
| [FLUX.2 [klein] 4B](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B) | Data set | turns vector art into the ten styles (kids' book, sci-fi, photo-realistic...) on the owner's PC |
| [PyTorch](https://pytorch.org) | Python package | ComfyUI's engine on the PC (CUDA 12.8 build, installed by worker/setup_comfyui.ps1) |
| [ComfyUI](https://github.com/comfyanonymous/ComfyUI) | Python package | the PC worker repaints each picture with FLUX.2 [klein] 4B through ComfyUI's local API |
| [Google Fonts](https://fonts.google.com) | Loaded from a CDN | IBM Plex Mono, Schibsted Grotesk |
| [Anvil Uplink](https://anvil.works/docs/uplink) | Python package | the PC worker registers imageenhancer_run/ping and says hello; the app's dispatcher calls it |

**Built into the browser:** Canvas 2D, localStorage, Clipboard.

**Anvil platform:** Anvil, Anvil Data Tables, Anvil JS bridge (anvil.js), Anvil Users, Anvil Google service, Anvil HTTP, Anvil Media, Anvil Secrets.

**Build and test tools (not shipped):** axe-core, Node.js, Headless Chrome (DevTools Protocol), PyYAML, Pillow.

<!-- libraries:end -->

## Working on it

See `.claude/skills/imageenhancer/SKILL.md`. In short:

```
python tools/check.py                    # Anvil's validator, JS syntax, asset hashes, server tests -> ALL CHECKS PASSED
python -I tools/ui_test.py               # the real app in the Anvil App Server (Docker) driven by headless Chrome
python -I tools/ui_test.py --shots DIR   # + screenshots of every page (desktop/phone, light/dark, guest/member)
python worker/tests/test_worker.py       # the worker against a fake ComfyUI -> WORKER TESTS PASSED
<venv with anvil-uplink + pillow>/python tools/testing/e2e_uplink.py   # real worker over Uplink -> E2E PASSED
git push origin master                   # deploy
```

## Project layout

```
client_code/    startup, router, state, fmt, auth, legal; Layouts/Shell; Pages/ Landing Auth Home(Queue) Job Try Keys Styles
                Setup(Connect) Profile Admin; Items/ JobRow EventRow StyleChip KeyRow StyleRow NavLink FeedbackRow UserRow;
                Dialogs/ KeyEdit KeyMade; Components/ BeforeAfter DevelopPrint
server_code/    Queue (jobs, ETA), Worker (dispatcher, Uplink, webhooks, tick), Api (HTTP), Console, Keys, Styles, Pictures,
                DemoData, Accounts, Admin, Feedback, SchemaCheck, common, legal_server
theme/assets/   app.css (Darkroom tokens + pages), ie-kit.js (SVG rasteriser, copy), app-kit.js, theme.css (spinner), icons
worker/         enhancer_worker.py, engines.py, workflows/, setup_comfyui.ps1, start_worker.bat, tests/ (fake ComfyUI)
clients/        enhancer_client.py (for other Anvil apps)
tools/          check.py, ui_test.py + ui/, testing/ (server tests, e2e_uplink.py), live/drive.mjs
```
