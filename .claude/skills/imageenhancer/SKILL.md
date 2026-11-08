---
name: imageenhancer
description: Context, workflow and recipes for Image Enhancer (folder image-enhancer), the user's Anvil app built as native Anvil Forms (Python + HTML templates, a layout, custom components, RepeatingPanels). A private image-restyling API for the user's other apps: a queue on Anvil, an owner-only console, and a PC worker (Anvil Uplink -> ComfyUI + FLUX.2 [klein] 4B) that repaints one picture at a time in one of ten styles. Load this before any feature request, bug fix, restyle, content change or deploy for this app.
---

# Image Enhancer: working on the app

**What it is:** a service, not a website. The user's other apps send a picture + style to the HTTP API
(`server_code/Api.py`, one key per app); jobs wait in a strict one-at-a-time queue (`Queue.py`); a background
dispatcher (`Worker.py`) calls the PC worker's Uplink function `imageenhancer_run`, saves the result, and if the PC is
away asks again every 15 minutes (or at once when the worker calls `enhancer_worker_hello`). Apps poll
`GET /v1/jobs/<id>` (position, ETA) or get a signed webhook. The console (owner only) has Queue, Job, Test bench, Apps &
keys, Styles, Connect. The PC side lives in `worker/` (setup_comfyui.ps1, start_worker.bat, enhancer_worker.py,
engines.py, workflows/flux2_klein_edit.json); `clients/enhancer_client.py` is the module other Anvil apps copy.

**Where it lives:**
- Folder `C:\Users\arkvi\Documents\CLAUDE\image-enhancer\` = the git clone of **github.com/arkulinskis/image-enhancer**, branch `master`.
  "git" layout: the folder *is* the Anvil app. Anvil pulls master; pushing is the deploy. Live: not published yet (then update `API` in clients/enhancer_client.py and the legal/SEO url).
- Made from `C:\Users\arkvi\Documents\CLAUDE\APP_MAKER\template-forms` (native Anvil Forms, Nov 2026). Anvil's own agent
  skills describe the same model: `client-forms`, `data-models`, `server-code`, `client-modules`, `anvil-yaml`
  (github.com/anvil-works/anvil-agent-references; see APP_MAKER/ANVIL_NOTES.md, "Native Anvil Forms").
- **README.md** lists every feature. Keep it up to date.

**What the user wants:** "an API with uplink" for their PC's image model: sequential jobs, ask again in 15 minutes
when the PC doesn't answer, a growing queue with ETAs on request, picture in -> restyled picture out (vector art ->
kids' book, sci-fi, realistic...), 10 options, no public site, secure for several apps. They asked Claude to choose the
model + method (ComfyUI + FLUX.2 [klein] 4B fp8, Apache 2.0; their PC: RTX 4070 Laptop 8 GB, 32 GB RAM).
Design: **Darkroom** (chosen 2026-11-07): dark by default (#131211, surfaces #1c1a18/#252220, ink #eeeae4), safelight red
brand (#ec6a50 dark / #b8381f light), amber accent #e9a23b (never as text), Schibsted Grotesk + IBM Plex Mono for ids/
numbers, radius 6-8px, hairlines, film-frame corner ticks (`.ie-frame`). Landing hero = a print developing in a tray
(Components/DevelopPrint, CSS + SVG only). Loader preset: fill. Claude assumes
details and builds; Claude deploys. Mobile-first: every page must fit 390 px. Light and dark.

## Workflow for any change

1. `git pull --ff-only` (Anvil commits "Edited ..." when the user changes something in the IDE; read those commits).
2. Edit: a page's template and Python side by side (`client_code/Pages/X/form_template.html` + `__init__.py`).
3. `python tools/check.py` (no -I) -> **ALL CHECKS PASSED**: Anvil's validator (`anvil validate`, type-checks every
   template and Python file against Anvil's API), JS syntax, asset hashes (`tools/assets.py`), server tests.
   Needs the Anvil CLI once: `npm install -g @anvil-works/anvil-cli`.
4. `python -I tools/ui_test.py` (Docker Desktop running) -> **ALL UI TESTS PASSED**: the folder runs as-is in the
   open-source Anvil App Server (container `imageenhancer-dev`) and headless Chrome walks tools/ui/flow.js, phone.js
   (true 390 px, no sideways scroll), admin.js and a11y.js (axe-core WCAG 2.2 AA on every page, light + dark, plus
   keyboard checks). Client edits show on reload; server edits need `--restart`. `--only a11y.js` runs one script.
   `--shots DIR` = screenshots of every page, desktop + phone, light + dark, guest + member: Read them.
5. Commit only your files as arkulinskis with the Co-Authored-By line; `git push origin master`.
   New tables/columns: tell the user to accept the **Schema Mismatch** alert ("The schema of the source code is correct").

## Architecture

```
anvil.yaml                 startup: module `startup`; db_schema; services; head_html (fonts, Prepsto, theme assets with ?v=)
client_code/
  startup.py               get_me, Privacy & Terms kit, router.start()
  router.py                PAGES (who may open each page), NAV (main menu), _form (page -> Form), go/href/replace
  state.py                 me(), call() (expected {"ok": False} -> toast + None), toast(), store, set_attr, dates
  auth.py                  sign in / up / reset / Continue with Google / sign out
  legal.py                 Privacy & Terms (installed from APP_MAKER/legal-kit; don't edit here)
  Layouts/Shell            header + account menu + footer + phone tab bar; slot "content"; refresh(page)
  Pages/                   Landing, Auth, Home (Queue), Job, Try, Keys, Styles, Setup (Connect), Profile, Admin
  Components/              BeforeAfter (slider), DevelopPrint (landing hero)
  Items/                   JobRow, EventRow, StyleChip, KeyRow, StyleRow, NavLink, FeedbackRow, UserRow
  Dialogs/                 KeyEdit, KeyMade
server_code/               common.py (C.*), Queue, Worker, Api, Console, Keys, Styles, Pictures, Accounts, Admin, DemoData, Feedback, SchemaCheck
theme/assets/              app.css (tokens + pages + the role layer), icons.css (generated), app-kit.js, theme.css
                           (loading spinner), icon.svg + PNGs (tools/make_icons.py)
tools/                     check.py, assets.py, build_icons.py, make_icons.py, ui_test.py + ui/, live/drive.mjs, testing/
```

## How things are done here

- **Page** = `client_code/Pages/X/` with `<anvil-form layout="Image_Enhancer.Layouts.Shell"><anvil-block slot="content">`
  and `class X(XTemplate)` taking `args=()` (the URL parts after `#x/`). Register it in router.py: `PAGES`, `_form`,
  and `NAV` if it belongs in the menu (max 4). Add its address to tools/ui/phone.js and its journey to flow.js.
- **The layout is reused between pages** (open_form keeps the Shell when the layout matches): anything in the Shell
  that depends on the user or the page goes in `Shell.refresh(page)`.
- **Navigation** = plain `<a href="#page">`; in code `router.go("page", arg)`; build links with `router.href`.
- **Static copy** = plain HTML in the template. **Text that changes** = a `Label` (role for the look).
- **Actions** = Anvil `Button` + `@handle("name", "click")`, roles `["btn", "btn-primary", "ic-plus"]`. Button roles
  are aliases of `.ui-btn` in app.css: `btn-primary`, `btn-ghost`, `btn-danger` + `btn-solid`, `btn-sm`, `btn-lg`,
  `btn-icon`, `btn-block`. Icons: role `ic-<name>` on Buttons/Links, `<i class="ic ic-<name>">` in HTML
  (names in app-kit.js `UI.ICONS`; add one there and run tools/build_icons.py).
- **Inputs** = TextBox / TextArea / DropDown / CheckBox (styled by app.css through `.ui input`, `.ui textarea`).
  Read `.text` / `.selected_value` / `.checked`; `pressed_enter` for Enter.
- **Plain HTML that changes** = `anvil:name="x"`, then `self.x.visible`, `self.x.classes["on"] = ...`,
  `self.x.style[...]`; attributes with `state.set_attr(self.x, "href", ...)`. Native clicks:
  `anvil:on-dom:click="self.x_click"` + `def x_click(self, event)`.
- **Lists** = `RepeatingPanel` + an `Items/` Form; never build repeated HTML strings. Bind fields in the item template
  (`bind:text="self.item['title']"`). Grid/flex CSS goes on the panel's items container: `.anvil-role-<role> > div`.
  Item -> page: `self.parent.raise_event("x-something", ...)` + `panel.add_event_handler("x-something", ...)`.
  Role `contents` lets a panel's items join the surrounding grid.
- **Dialogs** = a Form in `Dialogs/`, `alert(Form(...), buttons=[], role="app-dialog")`; it closes itself with
  `self.raise_event("x-close-alert", value=...)`. Yes/no: `confirm(text, title=..., buttons=[("Cancel", False), ("Delete", True)])`.
- **Toasts** = `state.toast(msg, "ok" | "error")` (Anvil Notification with roles).
- **Server calls** = `state.call("fn", ...)` for normal flows (expected `{"ok": False, "error"}` -> toast, returns None);
  a page that shows a friendly state instead (not found, private) calls `anvil.server.call` and checks `ok` itself.
  Server functions: `@anvil.server.callable(require_user=True)`, `C.require_user()` / `C.require_admin()`, ownership
  checks, return plain dicts (`C.ok(...)` / `C.fail("...")`), never other people's emails. Tables are `client: none`.
- **JavaScript** only for engines Python is too slow for (canvas, SVG drawing, WebGL, audio, maps, PDF): put it in
  `theme/assets/<name>.js`, load it in head_html (then `python tools/assets.py`), wrap it in one Python module
  (`from anvil.js import window`) and/or a `Components/` custom component. Little Hero Books is the worked example.

- **Accessibility (WCAG 2.2 AA, the legal bar; 2026-11-04)**: tools/ui/a11y.js runs axe-core on every page (light +
  dark, guest + member) and fails on serious problems; add new pages to its PUBLIC/MEMBER lists. The rules:
  - Text colours reach 4.5:1 on every surface: check new tokens (`--c-faint`, `--c-accent` used as text, status
    colours on their `-soft` fills). Text on good/bad/warn fills is `var(--c-on-status)` (white light, ink dark).
  - Every field has a name: wrap it in `<label class="ui-field"><span>Caption</span>...</label>`, or
    `state.set_control_attr(box, "aria-label", "...")` when the caption isn't a label (set it AFTER `.items` on a
    DropDown: Anvil rebuilds the select). Name/email/phone/password get `autocomplete` (set_control_attr).
  - The page's title Label is a heading: `state.heading(label, 1)` (one per page; Labels render as divs).
  - Toggle buttons say they're on: `.ui-seg` buttons get aria-pressed from the "on" class automatically (app-kit.js);
    elsewhere `state.set_control_attr(btn, "aria-pressed", ...)`. Never `role="tablist"` without real tabs.
  - Messages that appear are read out: roles msg-error/msg-note get role alert/status automatically; other changing
    Labels: `state.live(label)`. Hidden text just for screen readers: Label role `sr`.
  - When a click redraws a RepeatingPanel, keep the keyboard's place: give the item's button a `data-key` and call
    `state.refocus(panel, key)` after the event (PlanPlate's Items/Chip). Buttons have no `.focus()`: `state.focus(btn)`.
  - Images: content images get real alt text (photos: their caption); decorative ones `alt=""`; a Button icon image
    is set to alt="" automatically. Hidden anti-spam fields: `tabindex=-1`, `autocomplete=off`.

- **Design kit (2026-11-05)**: `APP_MAKER/design/README.md` is the bar for every visual change (craft floor, the
  "AI-made" tells, motion rules, worst-case data). app.css carries its CSS between `design-kit:start/end` (easing and
  duration tokens, browser surfaces, text wrapping, press feedback, gentle reduced motion): every transition uses
  `--ease-*` / `--dur-*`, no `ease-in`, no `transition: all`, no eyebrow labels, no gradient text. Checks:
  `python -I APP_MAKER/tools/design_check.py imageenhancer` (source; check.py prints its summary) and tools/ui/design.js
  (rendered, desktop + phone, inside ui_test.py; add new pages to its PUBLIC/MEMBER). Deliberate exceptions:
  `design-ok: <rule>` comment on the line.

## App map (Image Enhancer)

- **Jobs:** `jobs` table (job_id `job_xxxxxxxxxxxx`, status queued/working/done/failed/cancelled, priority, next_try,
  attempts, options {fidelity, megapixels, seed, format, size, extra, instruction}, source/result media + random
  source_key/result_key for `/v1/files/<key>` links). Never return rows; `Queue.job_dict` (API) / `console_dict` (console).
- **PC state** lives in app_settings under separate keys, one writer each: `pc_seen`, `pc_retry`, `pc_wake`,
  `dispatch` (lease: only one dispatcher runs; it renews every loop, 45 min while a job runs), `config`.
- **Dispatcher** `Worker.enhancer_dispatch` (background task) loops `Queue.next_ready()` -> `run_job`; "PC away" errors
  (NoServerFunctionError, UplinkDisconnectedError, TimeoutError...) put the job back without counting the try and set
  `pc_retry`; other errors retry after `retry_minutes` up to `max_attempts`. Waits in 15 s steps (`WAIT[0]` off in tests).
  `enhancer_tick` (scheduled, 15 min) recovers/purges/kicks. `Worker.kick()` is safe to call often.
- **Worker callables** `enhancer_worker_hello/bye` check `anvil.server.context.remote_caller.is_trusted` (server Uplink
  key only). The worker registers `imageenhancer_run(job, picture)` and `imageenhancer_ping()`.
- **ETA** `Queue.snapshot()`: average of the last 40 done jobs (per style with 3+ samples, default 90 s) + 4 s hand-over.
- **Styles** table seeded from `Styles.DEFAULTS` by `Styles.ensure()`; the worker gets the finished instruction.

## Recipes

- **Add a style:** append to `Styles.DEFAULTS` (key, label, blurb, instruction); `ensure()` adds it on next use. Add it to
  the landing's `.lp-styles` list and the server test's count (10).
- **Change the model/workflow:** `worker/workflows/*.json` (API format with `__PROMPT__` / `__INPUT__`), model files in
  `setup_comfyui.ps1` ($Models), file names checked by `ComfyEngine.prepare()`; update `worker/tests/fake_comfy.py`
  object_info if node names change. Keep the licence commercial-friendly (klein 9B is non-commercial).
- **Test the whole round trip:** `python -I tools/ui_test.py --only flow.js` (starts the App Server with the Uplink key
  `ie-local-test-server-uplink-key`), then with a Python that has anvil-uplink + pillow:
  `python tools/testing/e2e_uplink.py` (real worker + fake ComfyUI).

- **New table or column:** `db_schema` in anvil.yaml (same shape as the existing tables, `client: none`), then add it
  to server tests. Deploy, then the Schema Mismatch step. Personal data -> the legal kit (below).
- **New server function:** in a server module + tests in tools/testing/test_server.py (happy path, bad input,
  someone not allowed; public ones in `PUBLIC`).
- **Demo content:** DemoData.py (`is_demo=True`, `DEMO_TABLES`, children first).
- **Restyle:** tokens at the top of app.css (light and dark blocks), fonts in head_html, the spinner in theme.css
  (`python -I APP_MAKER/tools/loaders.py apply imageenhancer <preset>`), `LEGAL_THEME` in startup.py.
- **Icon:** edit theme/assets/icon.svg, `python -I tools/make_icons.py`, then `python tools/assets.py`.

## Gotchas

- **Raw image uploads:** with `Content-Type: image/png` Anvil may hand bits of the body to the endpoint as keyword
  "fields"; `Api.read_submission` reads options only from `request.query_params` there.
- **Errors from the worker** must not be named like the "away" errors (a worker `TimeoutError` would look like "PC away"):
  the worker raises everything as RuntimeError with a sentence; avoid "not connected" in messages.
- **Console pages are admin-only**; UI test scripts sign in as arkulinskis@gmail.com (`adminIn()`, password
  `Hb-local-admin-Kq7-2026` in the local test database only).
- A non-admin opening an owner page: router shows #home and `replaceState`s the address.
- Rows in RepeatingPanels keep `panel = self.parent` at the start of a click: a redraw during a dialog detaches the row.

- The local App Server (1.18) lags hosted Anvil: no `HtmlComponent.attrs` (use state.set_attr), `Notification(role=)`
  raises (state.toast falls back), notifications are `.anvil-alert[data-notify]`, components are wrapped in
  `<anvil-dropzone>` (app.css: `display: contents`). app.css styles both. Test on hosted Anvil too for big changes.
- Anvil's alert() without `large=True` is a 300 px modal: our role `app-dialog` widens it.
- Headless Chrome: Anvil's service worker breaks reused profiles (drive.mjs bypasses it); phone width needs device
  emulation (`MOBILE=390,844`), windows can't go below ~500 px.
- `require_secure_passwords` rejects leaked passwords: tests use random ones.
- Heredocs in the Bash tool mangle quotes: write files with the Write tool.
- A script's `el.focus()` doesn't always match `:focus-visible`, so tests check focus rings through the CSS rules,
  not computed styles. Never put `outline: none` on `input:focus` without `:not([type=checkbox]):not([type=radio])`.
- Never write Anvil's theme-colour token pattern (percent, `color:`, name, percent) in theme.css.

## Privacy & Terms (legal kit)

From `C:/Users/arkvi/Documents/CLAUDE/APP_MAKER/legal-kit`: change `apps/imageenhancer.json`, then there
`python -I build.py imageenhancer && python -I install.py imageenhancer` (writes theme/assets/legal-kit.js,
client_code/legal.py, server_code/legal_server.py and the head_html tag), then `python tools/assets.py` and deploy.
Sign-up keeps the tick box (`legal.consent_field()` in Pages/Auth). Feedback = Prepsto only ("Submit feedback").
- Client and server modules share ONE Python package: a server module can't have the same name as a client
  package or module (server `Items.py` + client `Items/` = "Cannot resolve imported module"). The template's example
  server module is `ExampleItems.py` for that reason.
