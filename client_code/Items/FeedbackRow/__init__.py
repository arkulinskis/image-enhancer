from anvil import *

from ._anvil_designer import FeedbackRowTemplate
from ... import state


class FeedbackRow(FeedbackRowTemplate):
    """Admin → Feedback: one older message (new feedback goes to Prepsto). Status buttons and Delete raise
    x-changed on the panel so the Admin page reloads the list."""

    def __init__(self, **properties):
        super().__init__(**properties)
        i = self.item
        self.kind.role = ["badge", "badge-bad" if i.get("kind") == "bug" else "badge-brand" if i.get("kind") == "idea" else "badge"]
        self.email_link.visible = bool(i.get("email"))
        self.email_link.url = "mailto:" + (i.get("email") or "")
        self.when.text = state.short_date(i.get("created"))
        c = i.get("context") or {}
        self.context.text = " · ".join(str(c[k]) for k in ("page", "screen", "theme", "browser") if c.get(k))
        for status, btn in (("new", self.new_button), ("read", self.read_button), ("done", self.done_button)):
            btn.role = ["btn", "btn-sm", "btn-primary"] if i.get("status") == status else ["btn", "btn-sm"]

    def _status(self, status):
        if state.call("set_feedback_status", self.item["id"], status, self.note_box.text or ""):
            state.toast("Saved", "ok")
            self.parent.raise_event("x-changed")

    @handle("new_button", "click")
    def new_button_click(self, **event_args):
        self._status("new")

    @handle("read_button", "click")
    def read_button_click(self, **event_args):
        self._status("read")

    @handle("done_button", "click")
    def done_button_click(self, **event_args):
        self._status("done")

    @handle("delete_button", "click")
    def delete_button_click(self, **event_args):
        if confirm("Delete this message?", buttons=[("Cancel", False), ("Delete", True)], role="app-dialog"):
            if state.call("delete_feedback", self.item["id"]) is not None:
                self.parent.raise_event("x-changed")
