from anvil import *

from ._anvil_designer import NavLinkTemplate
from ... import router, state


class NavLink(NavLinkTemplate):
    """A main-menu link (header and phone tab bar). item = {page, label, icon, on} from router.NAV."""

    def __init__(self, **properties):
        super().__init__(**properties)
        state.set_attr(self, "href", router.href(self.item["page"]))
        self.icon.classes.add("ic-" + self.item["icon"])
        self.classes["on"] = bool(self.item.get("on"))
