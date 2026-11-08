from anvil import *
import anvil.js

from ._anvil_designer import BeforeAfterTemplate
from ... import state


class BeforeAfter(BeforeAfterTemplate):
    """Before / after slider: the sent picture with the restyled one laid over it, revealed by dragging (or the arrow
    keys: it's a real range input). Without after_url it just shows the sent picture."""

    def __init__(self, **properties):
        self._before = ""
        self._after = ""
        self._labels = ["Sent", "Restyled"]
        super().__init__(**properties)
        self._draw()

    @property
    def before_url(self):
        return self._before

    @before_url.setter
    def before_url(self, value):
        self._before = value or ""
        self._draw()

    @property
    def after_url(self):
        return self._after

    @after_url.setter
    def after_url(self, value):
        self._after = value or ""
        self._draw()

    @property
    def before_label(self):
        return self._labels[0]

    @before_label.setter
    def before_label(self, value):
        self._labels[0] = value or "Sent"
        self._draw()

    @property
    def after_label(self):
        return self._labels[1]

    @after_label.setter
    def after_label(self, value):
        self._labels[1] = value or "Restyled"
        self._draw()

    def _draw(self):
        if getattr(self, "box", None) is None:
            return  # a property set before the template exists; __init__ draws again
        state.set_attr(self.before_img, "src", self._before or None)
        state.set_attr(self.after_img, "src", self._after or None)
        self.box.classes["no-after"] = not self._after
        anvil.js.get_dom_node(self.tag_before).textContent = self._labels[0]
        anvil.js.get_dom_node(self.tag_after).textContent = self._labels[1]

    def slider_input(self, event):
        anvil.js.get_dom_node(self.box).style.setProperty("--pos", "%s%%" % event.target.value)
