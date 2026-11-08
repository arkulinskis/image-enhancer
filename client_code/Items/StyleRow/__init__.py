import anvil.server
from anvil import *

from ._anvil_designer import StyleRowTemplate
from ... import state


class StyleRow(StyleRowTemplate):
    """One editable style on the Styles page. item = a style dict from styles_list."""

    def __init__(self, **properties):
        super().__init__(**properties)
        self._fill(self.item)
        state.set_control_attr(self.enabled_box, "aria-label", "%s is switched on" % self.item["label"])

    def _fill(self, s):
        self.label_box.text, self.blurb_box.text, self.prompt_box.text = s["label"], s["blurb"], s["prompt"]
        self.enabled_box.checked = s["enabled"]
        self.key_label.text = "key: %s%s" % (s["key"], " · changed" if s["changed"] else "")
        self.reset_button.visible = s["changed"]
        self.message.visible = False

    @handle("save_button", "click")
    def save_button_click(self, **event_args):
        self.save_button.enabled = False
        try:
            r = anvil.server.call("style_save", self.item["key"], self.label_box.text or "", self.blurb_box.text or "",
                                  self.prompt_box.text or "", self.enabled_box.checked)
        finally:
            self.save_button.enabled = True
        if not r.get("ok"):
            self.message.text, self.message.visible = r.get("error") or "That didn't work.", True
            return
        self.item = r["style"]
        self._fill(r["style"])
        state.toast("Saved %s." % r["style"]["label"], "ok")

    @handle("reset_button", "click")
    def reset_button_click(self, **event_args):
        r = state.call("style_reset", self.item["key"])
        if r:
            self.item = r["style"]
            self._fill(r["style"])
            state.toast("Back to the original words.", "ok")
