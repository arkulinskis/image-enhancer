from anvil import *

from ._anvil_designer import UserRowTemplate
from ... import state


class UserRow(UserRowTemplate):
    """Admin → Users: one person with the Admin and Active switches (saved straight away)."""

    def __init__(self, **properties):
        super().__init__(**properties)
        self.joined.text = state.short_date(self.item.get("joined"))

    def _save(self, fn, box):
        r = state.call(fn, self.item["id"], box.checked)
        if r:
            state.toast("Saved", "ok")
        else:
            box.checked = not box.checked  # the server said no (e.g. your own admin switch): put it back

    @handle("admin_box", "change")
    def admin_box_change(self, **event_args):
        self._save("set_admin", self.admin_box)

    @handle("active_box", "change")
    def active_box_change(self, **event_args):
        self._save("set_enabled", self.active_box)
