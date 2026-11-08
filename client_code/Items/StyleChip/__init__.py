from anvil import *

from ._anvil_designer import StyleChipTemplate
from ... import state


class StyleChip(StyleChipTemplate):
    """One style to pick on the test bench. item = {key, label, description, on}. Raises x-pick with the key."""

    def __init__(self, **properties):
        super().__init__(**properties)
        on = bool(self.item.get("on"))
        self.chip.role = ["ie-chip", "on"] if on else ["ie-chip"]
        self.chip.tooltip = self.item.get("description") or ""
        state.set_control_attr(self.chip, "aria-pressed", "true" if on else "false")
        state.set_control_attr(self.chip, "data-key", self.item["key"])

    @handle("chip", "click")
    def chip_click(self, **event_args):
        self.parent.raise_event("x-pick", key=self.item["key"])
