from anvil import *

from ._anvil_designer import KeysTemplate
from ... import state


class Keys(KeysTemplate):
    """#keys: the apps allowed to send pictures. New key / edit / replace / delete; a new key is shown once in the
    KeyMade dialog."""

    def __init__(self, args=(), **properties):
        super().__init__(**properties)
        state.heading(self.title, 1)
        self.keys_panel.add_event_handler("x-changed", self._load)
        self._load()

    def _load(self, **event_args):
        d = state.call("keys_list")
        self.keys_panel.items = d["clients"]
        self.empty.visible = not d["clients"]

    @handle("new_button", "click")
    def new_button_click(self, **event_args):
        from ...Dialogs.KeyEdit import KeyEdit
        made = alert(KeyEdit(), buttons=[], role="app-dialog")
        if made:
            from ...Dialogs.KeyMade import KeyMade
            alert(KeyMade(made=made), buttons=[], role="app-dialog", large=True)
            self._load()
