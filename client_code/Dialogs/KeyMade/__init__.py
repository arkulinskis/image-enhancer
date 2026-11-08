from anvil import *
from anvil.js import window

from ._anvil_designer import KeyMadeTemplate
from ... import state


class KeyMade(KeyMadeTemplate):
    """Shows a new key and webhook secret once, with Copy buttons. made = the reply of key_create / key_rotate."""

    def __init__(self, made, **properties):
        super().__init__(**properties)
        self.made = made
        self.heading.text = "Key for %s" % made["client"]["name"]
        self.key_text.text = made["key"]
        self.secret_text.text = made["webhook_secret"]

    def _copy(self, text):
        if window.IE.copy(text):
            state.toast("Copied.", "ok")
        else:
            state.toast("Your browser blocked copying: select the text and copy it by hand.", "error")

    @handle("copy_key", "click")
    def copy_key_click(self, **event_args):
        self._copy(self.made["key"])

    @handle("copy_secret", "click")
    def copy_secret_click(self, **event_args):
        self._copy(self.made["webhook_secret"])

    @handle("done_button", "click")
    def done_button_click(self, **event_args):
        self.raise_event("x-close-alert", value=True)
