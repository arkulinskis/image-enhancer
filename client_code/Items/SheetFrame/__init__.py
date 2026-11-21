from anvil import *

from ._anvil_designer import SheetFrameTemplate
from ... import fmt, router, state


class SheetFrame(SheetFrameTemplate):
    """One frame of a contact sheet. item = a console job dict + "_n" (frame number, 0 = the original picture).
    Shows the result once it's done; until then the status ("developing...", position, error)."""

    def __init__(self, **properties):
        super().__init__(**properties)
        j = self.item
        n = j.get("_n", 0)
        original = n == 0
        self.num.text = "Original" if original else "%02d" % n
        self.label.text = (j.get("source_name") or "The picture") if original else j["style_label"]
        url = j.get("source_url") if original else j.get("result_url")
        state.set_attr(self.frame, "href", router.href("job", j["id"]))
        self.pic.classes["empty"] = not url
        self.pic.classes["failed"] = j["status"] in ("failed", "cancelled") and not original
        if url:
            state.set_attr(self.img, "src", url)
            state.set_attr(self.img, "alt", "The original picture" if original else "The picture as %s" % j["style_label"])
        self.img.visible = bool(url)
        self.wait.visible = not url
        if original:
            self.note.text = fmt.size(j["width"], j["height"]) or ""
        elif j["status"] == "done":
            self.note.text = "%s · seed %s" % (fmt.secs(j["seconds"]), j["seed"]) if j.get("seed") is not None else fmt.secs(j["seconds"])
        elif j["status"] == "working":
            self.wait.text = "Developing..."
            self.note.text = "on the PC, ready %s" % fmt.eta(j["eta_seconds"])
        elif j["status"] == "queued":
            self.wait.text = "In the queue"
            self.note.text = "number %s · ready %s" % (j["position"], fmt.eta(j["eta_seconds"])) if j.get("eta_seconds") is not None else "number %s" % j["position"]
        else:
            self.wait.text = fmt.STATUS.get(j["status"], j["status"])
            self.note.text = (j.get("diagnosis") or {}).get("title") or (j.get("error") or "")
