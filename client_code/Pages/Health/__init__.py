from anvil import *
import json

import anvil.js
from anvil.js import window

from ._anvil_designer import HealthTemplate
from ... import fmt, state


def _pct(v):
    return "-" if v is None else "%d%%" % v


def _gap(minutes):
    if not minutes:
        return "none"
    if minutes < 60:
        return "%d min" % minutes
    h, m = divmod(int(minutes), 60)
    return ("%d h %d min" % (h, m)) if m and h < 10 else "%d h" % h


class Health(HealthTemplate):
    """#health: when the PC was connected over the last 7 days (an hour-by-hour map drawn by IE.heatmap in
    ie-kit.js), what it made, how fast each style is, and what went wrong with the likely causes. Refreshes every
    minute while open."""

    def __init__(self, args=(), **properties):
        super().__init__(**properties)
        state.heading(self.title, 1)
        self.problems_panel.add_event_handler("x-retry", self._retry_cause)
        self._load(False)
        self.timer.interval = 60

    def _load(self, quiet):
        tz = -int(anvil.js.new(window.Date).getTimezoneOffset())
        d = state.call_quiet("console_health", tz) if quiet else state.call("console_health", tz)
        if d:
            self._draw(d)

    def _draw(self, d):
        w = d.get("worker") or {}
        version = ("worker " + w["version"]) if w.get("version") else None
        bits = [b for b in (w.get("gpu"), w.get("model"), w.get("host"), version) if b]
        pc = d.get("pc") or {}
        seen = ("last seen " + fmt.ago(d["last_seen"])) if d.get("last_seen") else "never seen yet"
        self.sub.text = "%s · %s" % (fmt.PC_STATE.get(pc.get("state"), "The PC"), " · ".join(bits + [seen]))
        self.n_up24.text = _pct(d["uptime_24"])
        self.n_up7.text = _pct(d["uptime_7"])
        self.n_gap.text = _gap(d["longest_gap_minutes"]) if d["uptime_7"] is not None else "-"
        self.n_done24.text = str(d["done_24"])
        self.n_fail.text = ("%d (%d%%)" % (d["failed_7"], d["fail_rate_7"])) if d["fail_rate_7"] is not None else "0"
        self.n_avg.text = fmt.secs(d["avg_7"]) if d["avg_7"] else "-"
        has = bool(d.get("since"))
        self.since.text = ("Recorded since %s" % fmt.clock(d["since"])) if has else ""
        self.no_heat.visible = not has
        node = anvil.js.get_dom_node(self.heat)
        window.IE.heatmap(node, window.JSON.parse(json.dumps(d["days"])))
        if has:
            label = "The PC was connected %s of the time this week and %s in the last 24 hours." % (
                _pct(d["uptime_7"]), _pct(d["uptime_24"]))
        else:
            label = "No record of the PC yet."
        node.setAttribute("aria-label", label)
        days = [{"label": "Day", "a": "There", "b": "Done / failed", "c": "Per picture", "head": True}]
        for x in reversed(d["days"]):
            days.append({"label": x["label"], "a": _pct(x["uptime"]), "b": "%d / %d" % (x["done"], x["failed"]),
                         "c": fmt.secs(x["avg"]) if x["avg"] else "-"})
        self.days_panel.items = days
        rows = [{"label": "Style", "a": "Done", "b": "Failed", "c": "Per picture", "head": True}]
        for s in d["styles"]:
            rows.append({"label": s["label"], "a": str(s["done"]), "b": str(s["failed"]),
                         "c": fmt.secs(s["avg"]) if s["avg"] else "-"})
        self.styles_panel.items = rows if d["styles"] else []
        self.no_styles.visible = not d["styles"]
        self.problems_panel.items = d["problems"]
        self.no_problems.visible = not d["problems"]

    def _retry_cause(self, key, **event_args):
        r = state.call("console_retry_failed", key)
        if r:
            state.toast("%s back in the queue." % state.plural(r["count"], "picture"), "ok")
            self._load(False)

    @handle("refresh_button", "click")
    def refresh_button_click(self, **event_args):
        self._load(False)

    @handle("timer", "tick")
    def timer_tick(self, **event_args):
        self._load(True)
