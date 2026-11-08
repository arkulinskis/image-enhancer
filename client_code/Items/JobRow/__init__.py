from anvil import *

from ._anvil_designer import JobRowTemplate
from ... import fmt, router, state


class JobRow(JobRowTemplate):
    """One job in the Queue page's lists. item = a console job dict + "_mode": "wait" (position, estimate, Do next,
    Cancel) or "recent" (before + after thumbnails, time taken). Raises x-changed on the panel after an action."""

    def __init__(self, **properties):
        super().__init__(**properties)
        j = self.item
        wait = j.get("_mode") == "wait"
        link = router.href("job", j["id"])
        state.set_attr(self.pair, "href", link)
        state.set_attr(self.title_link, "href", link)
        state.set_attr(self.pair, "aria-label", "Open %s" % j["id"])
        self.row.classes["recent"] = not wait
        self.pos.visible = wait
        if wait:
            self.pos.text = "now" if j["status"] == "working" else str(j["position"] or "")
            self.pos.role = ["ie-pos", "now"] if j["status"] == "working" else ["ie-pos"]
        self.pair.classes["single"] = wait or not j.get("result_url")
        self.res_box.visible = not wait and bool(j.get("result_url"))
        state.set_attr(self.src_img, "src", j.get("source_url") or "")
        if j.get("result_url") and not wait:
            state.set_attr(self.res_img, "src", j["result_url"])
        self.style_label.text = j["style_label"]
        self.status.text = fmt.STATUS.get(j["status"], j["status"])
        self.status.role = ["st", "st-" + j["status"]]
        bits = [j["app"]]
        if j.get("ref"):
            bits.append(j["ref"])
        bits.append(j["id"])
        if wait:
            bits.append("sent " + fmt.ago(j["created"]))
        else:
            bits.append(fmt.clock(j["finished"] or j["created"]))
        if j.get("demo"):
            bits.append("demo")
        self.meta.text = " · ".join(bits)
        self.err.visible = bool(j.get("error")) and j["status"] in ("failed", "queued")
        self.err.text = j.get("error") or ""
        if wait:
            if j["status"] == "working":
                self.eta.text = "done " + fmt.eta(j["eta_seconds"])
            elif j.get("next_try_at") and (fmt.until(j["next_try_at"]) or 0) > 0:
                self.eta.text = "next try " + fmt.clock(j["next_try_at"])
            else:
                self.eta.text = fmt.eta(j["eta_seconds"]) if j["eta_seconds"] is not None else "paused"
            self.next_button.visible = j["status"] == "queued" and (j["position"] or 0) > 1
            self.cancel_button.visible = j["status"] == "queued"
        else:
            self.eta.text = fmt.secs(j["seconds"]) if j["status"] == "done" else ""

    @handle("next_button", "click")
    def next_button_click(self, **event_args):
        panel = self.parent
        if state.call("console_next", self.item["id"]):
            state.toast("%s is next." % self.item["id"], "ok")
            _changed(panel)

    @handle("cancel_button", "click")
    def cancel_button_click(self, **event_args):
        panel = self.parent
        if confirm("The app that sent it will see it as cancelled.", title="Cancel this picture?",
                   buttons=[("Keep it", False), ("Cancel it", True)], role="app-dialog"):
            if state.call("console_cancel", self.item["id"]):
                _changed(panel)


def _changed(panel):
    """Tell the page to reload its list (the panel may already have redrawn without this row)."""
    if panel is not None:
        panel.raise_event("x-changed")
