from anvil import *

from ._anvil_designer import DevelopPrintTemplate


class DevelopPrint(DevelopPrintTemplate):
    """The landing page's hero: a flat vector print develops in a darkroom tray, then a wipe repaints it as a
    picture-book illustration. All CSS + inline SVG (app.css: .ie-tray, .dev-flat, .dev-paint), so it shows even if
    nothing else runs; with reduced motion it only fades."""

    def __init__(self, **properties):
        super().__init__(**properties)
