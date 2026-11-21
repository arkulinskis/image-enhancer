from anvil import *
import anvil.server

from ._anvil_designer import SheetTemplate
from ... import router, state


class Sheet(SheetTemplate):
    """#sheet/<sheet id>: one picture in several styles side by side (made on the Test bench), frames developing as
    the PC paints them. Watches every 4 s while any frame is still waiting or on the PC."""

    def __init__(self, args=(), **properties):
        super().__init__(**properties)
        self.sheet_id = args[0] if args else ""
        state.heading(self.title, 1)
        state.live(self.progress)
        self._key = None
        self._load(anvil.server.call("console_sheet", self.sheet_id))

    def _load(self, r):
        if not r or not r.get("ok"):
            self.missing.visible, self.body.visible = True, False
            self.missing_text.text = (r or {}).get("error") or "It may have been deleted."
            self.again_button.visible = False
            self.timer.interval = 0
            return
        self.missing.visible, self.body.visible = False, True
        jobs = r["jobs"]
        done = len([j for j in jobs if j["status"] == "done"])
        open_ = [j for j in jobs if j["status"] in ("queued", "working")]
        bad = len([j for j in jobs if j["status"] in ("failed", "cancelled")])
        opts = "%s · %s MP · seed %s" % (r["fidelity"], r["megapixels"], r["seed"])
        if r.get("prompt"):
            opts += " · “%s”" % r["prompt"]
        self.sub.text = "%s in %s · %s" % (r["source_name"] or "Picture", state.plural(len(jobs), "style"), opts)
        if open_:
            self.progress.text = "%d of %d developed. The rest are in the queue; this page fills in by itself." % (done, len(jobs))
        elif bad:
            self.progress.text = "%d of %d developed, %d didn't work (open a frame to see why)." % (done, len(jobs), bad)
        else:
            self.progress.text = "All %d developed. Which style suits this picture best?" % len(jobs)
        key = repr([(j["id"], j["status"], j.get("position")) for j in jobs])
        if key != self._key:
            self._key = key
            original = dict(jobs[0], _n=0)
            self.frames_panel.items = [original] + [dict(j, _n=i + 1) for i, j in enumerate(jobs)]
        self.again_button.visible = not open_
        self.timer.interval = 4 if open_ else 0

    @handle("timer", "tick")
    def timer_tick(self, **event_args):
        r = state.call_quiet("console_sheet", self.sheet_id)
        if r:
            self._load(r)

    @handle("again_button", "click")
    def again_button_click(self, **event_args):
        r = state.call("console_sheet_again", self.sheet_id)
        if r:
            state.toast("A new sheet is in the queue, with a new seed.", "ok")
            router.go("sheet", r["sheet_id"])
