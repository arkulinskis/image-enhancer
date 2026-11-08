from anvil import *
import anvil.js
import anvil.media
import anvil.server
from anvil.js import window

from ._anvil_designer import TryTemplate
from ... import fmt, router, state

MEGAPIXELS = [("0.5 MP (fast)", 0.5), ("0.75 MP", 0.75), ("1 MP", 1.0), ("1.5 MP", 1.5), ("2 MP (slow)", 2.0)]
SIZES = [("Model size", "model"), ("Same as sent", "source")]
FORMATS = [("PNG", "png"), ("JPEG", "jpeg"), ("WebP", "webp")]


class Try(TryTemplate):
    """#try, the test bench: choose a picture (SVG is drawn into a PNG in the browser), a style and the options, send
    it through the real queue (console_submit), then watch the job until the PC is done."""

    def __init__(self, args=(), **properties):
        super().__init__(**properties)
        state.heading(self.title, 1)
        state.live(self.result_state)
        self.picture = None
        self._url = None
        self.style = state.store_get("try.style", "kids_book")
        self.fidelity = state.store_get("try.fidelity", "balanced")
        self.job_id = None
        d = state.call("console_styles")
        self.styles = d["styles"]
        if self.style not in [s["key"] for s in self.styles] and self.styles:
            self.style = self.styles[0]["key"]
        self.styles_panel.add_event_handler("x-pick", self._pick)
        self.mp_drop.items, self.mp_drop.selected_value = MEGAPIXELS, 1.0
        self.size_drop.items, self.size_drop.selected_value = SIZES, "model"
        self.fmt_drop.items, self.fmt_drop.selected_value = FORMATS, "png"
        for box, label in ((self.mp_drop, "Detail"), (self.size_drop, "Result size"), (self.fmt_drop, "File type")):
            state.set_control_attr(box, "aria-label", label)
        state.set_control_attr(self.prompt_box, "aria-label", "Extra words for the model")
        self._draw_styles()
        self._draw_fidelity()
        self._show_picture()
        self.result_box.visible = False

    # ---- picture
    def _show_picture(self):
        has = self.picture is not None
        self.drop.visible = not has
        self.preview_box.visible = has
        self.file_row.visible = has
        if has:
            state.set_attr(self.preview_img, "src", self._url.url if self._url else None)

    @handle("loader", "change")
    def loader_change(self, file, **event_args):
        if file is None:
            return
        self.message.visible = False
        name = getattr(file, "name", None) or "picture"
        ctype = (file.content_type or "").lower()
        if ctype not in ("image/png", "image/jpeg", "image/webp", "image/svg+xml") and not name.lower().endswith(".svg"):
            self._error("That file isn't a PNG, JPEG, WebP or SVG picture.")
            return
        if ctype == "image/svg+xml" or name.lower().endswith(".svg"):
            tmp = anvil.media.TempUrl(file)
            try:
                blob = window.IE.rasterize(tmp.url, 1536)
            except Exception:
                self._error("Your browser couldn't draw that SVG. Export it as a PNG instead.")
                return
            finally:
                tmp.revoke()
            file = anvil.js.to_media(blob)
            name = name.rsplit(".", 1)[0] + ".png"
        if file.length > 15 * 1024 * 1024:
            self._error("That picture is over 15 MB. Make it smaller first.")
            return
        self.picture, self.picture_name = file, name
        if self._url:
            self._url.revoke()
        self._url = anvil.media.TempUrl(file)
        self.file_label.text = "%s · %.1f MB" % (name, file.length / 1048576.0) if file.length >= 1048576 else "%s · %d KB" % (name, max(1, file.length // 1024))
        self._show_picture()

    @handle("clear_button", "click")
    def clear_button_click(self, **event_args):
        self.picture = None
        self.loader.clear()
        self._show_picture()

    # ---- style + fidelity
    def _draw_styles(self):
        key = state.focus_key()
        self.styles_panel.items = [dict(s, on=s["key"] == self.style) for s in self.styles]
        chosen = [s for s in self.styles if s["key"] == self.style]
        self.style_note.text = chosen[0]["description"] if chosen else ""
        state.refocus(self.styles_panel, key)

    def _pick(self, key, **event_args):
        self.style = key
        state.store_set("try.style", key)
        self._draw_styles()

    def _draw_fidelity(self):
        for name, btn in (("loose", self.fid_loose), ("balanced", self.fid_balanced), ("strict", self.fid_strict)):
            btn.role = ["seg", "on"] if name == self.fidelity else ["seg"]
            state.set_control_attr(btn, "aria-pressed", "true" if name == self.fidelity else "false")

    def _set_fidelity(self, value):
        self.fidelity = value
        state.store_set("try.fidelity", value)
        self._draw_fidelity()

    @handle("fid_loose", "click")
    def fid_loose_click(self, **event_args):
        self._set_fidelity("loose")

    @handle("fid_balanced", "click")
    def fid_balanced_click(self, **event_args):
        self._set_fidelity("balanced")

    @handle("fid_strict", "click")
    def fid_strict_click(self, **event_args):
        self._set_fidelity("strict")

    # ---- send + watch
    def _error(self, text):
        self.message.text, self.message.visible = text, True

    @handle("send_button", "click")
    def send_button_click(self, **event_args):
        if self.picture is None:
            self._error("Choose a picture first.")
            return
        seed = (self.seed_box.text or "").strip() if isinstance(self.seed_box.text, str) else self.seed_box.text
        self.message.visible = False
        self.send_button.enabled = False
        try:
            r = anvil.server.call("console_submit", self.picture, self.style, self.prompt_box.text or "", self.fidelity,
                                  self.mp_drop.selected_value, self.fmt_drop.selected_value, self.size_drop.selected_value,
                                  seed if seed not in ("", None) else None)
        finally:
            self.send_button.enabled = True
        if not r.get("ok"):
            self._error(r.get("error") or "That didn't work.")
            return
        self.job_id = r["job"]["id"]
        state.toast("Sent. It's number %s in the queue." % (r["job"]["position"] or 1), "ok")
        self._show_job(r["job"])
        self.timer.interval = 3

    def _show_job(self, j):
        self.result_box.visible = True
        state.set_attr(self.job_link, "href", router.href("job", j["id"]))
        self.compare.before_url = j["source_url"] or ""
        self.compare.after_url = j["result_url"] or ""
        if j["status"] == "done":
            self.result_state.text = "Done in %s. Drag across the picture to compare." % fmt.secs(j["seconds"])
        elif j["status"] == "working":
            self.result_state.text = "The PC is painting it. Ready %s." % fmt.eta(j["eta_seconds"])
        elif j["status"] == "queued":
            if j.get("next_try_at"):
                self.result_state.text = "Waiting for the PC (number %s). It's asked again at %s, or as soon as it connects." % (
                    j["position"], fmt.clock(j["next_try_at"]))
            else:
                self.result_state.text = "Number %s in the queue, ready %s." % (j["position"], fmt.eta(j["eta_seconds"]))
        else:
            self.result_state.text = "%s: %s" % (fmt.STATUS.get(j["status"], j["status"]), j["error"] or "")
        if j["status"] not in ("queued", "working"):
            self.timer.interval = 0

    @handle("timer", "tick")
    def timer_tick(self, **event_args):
        if not self.job_id:
            self.timer.interval = 0
            return
        r = state.call_quiet("console_job", self.job_id)
        if r and r.get("ok"):
            self._show_job(r["job"])
