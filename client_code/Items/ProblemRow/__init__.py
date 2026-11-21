from anvil import *

from ._anvil_designer import ProblemRowTemplate
from ... import router, state


class ProblemRow(ProblemRowTemplate):
    """One cause in the "Needs attention" card (Queue) and on the Health page. item = a group from
    Diagnose.problems: {key, title, steps, failed, retrying, retryable, demo, job_id, error}. Raises x-retry with
    the cause's key when "Try these again" is pressed."""

    def __init__(self, **properties):
        super().__init__(**properties)
        g = self.item
        self.title.text = g["title"]
        bits = []
        if g["failed"]:
            bits.append("%d failed" % g["failed"])
        if g["retrying"]:
            bits.append("%d waiting to retry" % g["retrying"])
        self.count.text = " · ".join(bits)
        self.count.role = ["st", "st-failed"] if g["failed"] else ["st", "st-queued"]
        self.steps.text = "\n".join("• " + s for s in g["steps"])
        self.latest.text = "Latest: %s%s" % (g["job_id"] or "", (" · " + g["error"]) if g["error"] else "")
        state.set_attr(self.title_link, "href", router.href("job", g["job_id"]) if g["job_id"] else "#home")
        self.retry_button.visible = g["retryable"] > 0
        self.retry_button.text = "Try %s again" % ("it" if g["retryable"] == 1 else "these %d" % g["retryable"])

    @handle("retry_button", "click")
    def retry_button_click(self, **event_args):
        self.parent.raise_event("x-retry", key=self.item["key"])
