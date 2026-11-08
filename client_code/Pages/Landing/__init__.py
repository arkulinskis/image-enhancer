from anvil import *

from ._anvil_designer import LandingTemplate
from ... import state


class Landing(LandingTemplate):
    """#landing, the About page: what the private service does, how the queue works, the ten styles, questions.
    Static copy lives in the template; only the signed-in variations are set here."""

    def __init__(self, args=(), **properties):
        super().__init__(**properties)
        me = state.me()
        self.guest_cta.visible = not me
        self.signup_line.visible = not me
        self.member_cta.visible = bool(me)
