from anvil import *

from ._anvil_designer import EventRowTemplate
from ... import fmt


class EventRow(EventRowTemplate):
    """One line of the Queue page's activity list. item = {time, kind, text, job_id}."""

    def __init__(self, **properties):
        super().__init__(**properties)
        self.when.text = fmt.clock(self.item["time"])
