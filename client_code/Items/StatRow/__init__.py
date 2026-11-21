from anvil import *

from ._anvil_designer import StatRowTemplate


class StatRow(StatRowTemplate):
    """One row of a small table on the Health page. item = {label, a, b, c, head?} (already formatted text);
    head=True draws the column captions."""

    def __init__(self, **properties):
        super().__init__(**properties)
        head = bool(self.item.get("head"))
        for comp, key in ((self.a, "a"), (self.b, "b"), (self.c, "c")):
            v = self.item.get(key)
            comp.text = "-" if v is None or v == "" else str(v)
            comp.role = ["ie-stat-head"] if head else ["mono"]
        if head:
            self.label.role = ["ie-stat-head"]
