from anvil import *

from ._anvil_designer import StylesTemplate
from ... import state


class Styles(StylesTemplate):
    """#styles: edit each style's name, blurb and instruction; switch styles on or off; reset to the original words."""

    def __init__(self, args=(), **properties):
        super().__init__(**properties)
        state.heading(self.title, 1)
        d = state.call("styles_list")
        self.styles_panel.items = d["styles"]
        self.fid_loose.text = d["fidelity"]["loose"]
        self.fid_balanced.text = d["fidelity"]["balanced"]
        self.fid_strict.text = d["fidelity"]["strict"]
