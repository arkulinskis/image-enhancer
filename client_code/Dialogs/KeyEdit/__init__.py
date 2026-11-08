import anvil.server
from anvil import *

from ._anvil_designer import KeyEditTemplate
from ... import state


class KeyEdit(KeyEditTemplate):
    """Make a new key (client=None) or change one (name, hourly limit, note, on/off). Closes with the server's reply
    (for a new key it holds the key and webhook secret, shown next in KeyMade), or None."""

    def __init__(self, client=None, **properties):
        super().__init__(**properties)
        self.client = client
        self.active_row.visible = client is not None
        if client:
            self.heading.text = "Edit %s" % client["name"]
            self.name_box.text = client["name"]
            self.limit_box.text = client["hourly_limit"]
            self.note_box.text = client["note"]
            self.active_box.checked = client["active"]
            self.save_button.text = "Save"
            self.save_button.role = ["btn", "btn-primary", "ic-check"]

    @handle("", "show")
    def form_show(self, **event_args):
        self.name_box.focus()

    @handle("cancel_button", "click")
    def cancel_button_click(self, **event_args):
        self.raise_event("x-close-alert", value=None)

    @handle("name_box", "pressed_enter")
    def name_box_pressed_enter(self, **event_args):
        self.save_button_click()

    @handle("save_button", "click")
    def save_button_click(self, **event_args):
        name = (self.name_box.text or "").strip()
        if len(name) < 2:
            self.message.text, self.message.visible = "Name the app this key is for (at least 2 characters).", True
            return
        limit = self.limit_box.text or 60
        self.save_button.enabled = False
        try:
            if self.client:
                r = anvil.server.call("key_update", self.client["id"], name, limit, self.active_box.checked, self.note_box.text or "")
            else:
                r = anvil.server.call("key_create", name, limit, self.note_box.text or "")
        finally:
            self.save_button.enabled = True
        if not r.get("ok"):
            self.message.text, self.message.visible = r.get("error") or "That didn't work.", True
            return
        state.toast("Saved." if self.client else "Key made.", "ok")
        self.raise_event("x-close-alert", value=r)
