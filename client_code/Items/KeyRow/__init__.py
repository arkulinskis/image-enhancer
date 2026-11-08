from anvil import *

from ._anvil_designer import KeyRowTemplate
from ... import fmt, state


class KeyRow(KeyRowTemplate):
    """One app's key on the Apps & keys page. item = a client dict from keys_list. Raises x-changed after a change."""

    def __init__(self, **properties):
        super().__init__(**properties)
        c = self.item
        self.state_badge.text = "On" if c["active"] else "Off"
        self.state_badge.role = ["st", "st-done"] if c["active"] else ["st"]
        self.prefix.text = "%s... · up to %d pictures an hour" % (c["prefix"], c["hourly_limit"])
        self.usage.text = "%s sent%s" % (state.plural(c["jobs_total"], "picture"),
                                         (" · %d waiting" % c["waiting"]) if c["waiting"] else "")
        self.used.text = "Last used %s" % fmt.ago(c["last_used"]) if c["last_used"] else "Not used yet"
        self.rotate_button.visible = not c["demo"]
        self.edit_button.visible = not c["demo"]

    @handle("edit_button", "click")
    def edit_button_click(self, **event_args):
        panel = self.parent
        from ...Dialogs.KeyEdit import KeyEdit
        if alert(KeyEdit(client=self.item), buttons=[], role="app-dialog"):
            _changed(panel)

    @handle("rotate_button", "click")
    def rotate_button_click(self, **event_args):
        panel = self.parent
        if confirm("The app's current key stops working at once. You'll get a new key and webhook secret to paste into the app.",
                   title="Replace the key for %s?" % self.item["name"], buttons=[("Cancel", False), ("Replace it", True)],
                   role="app-dialog"):
            r = state.call("key_rotate", self.item["id"])
            if r:
                from ...Dialogs.KeyMade import KeyMade
                alert(KeyMade(made=r), buttons=[], role="app-dialog", large=True)
                _changed(panel)

    @handle("delete_button", "click")
    def delete_button_click(self, **event_args):
        panel = self.parent
        if confirm("The key stops working and the app's waiting pictures are cancelled. Finished jobs stay in the history.",
                   title="Delete the key for %s?" % self.item["name"], buttons=[("Cancel", False), ("Delete", True)],
                   role="app-dialog"):
            if state.call("key_delete", self.item["id"]) is not None:
                _changed(panel)


def _changed(panel):
    """Tell the page to reload its list (the panel may already have redrawn without this row)."""
    if panel is not None:
        panel.raise_event("x-changed")
