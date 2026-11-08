from anvil import *

from ._anvil_designer import HomeTemplate
from ... import fmt, state


class Home(HomeTemplate):
    """#home, the Queue: the PC's state, what's waiting (with estimated finish times), recent results, activity.
    Refreshes quietly every 8 seconds while it's on screen. Non-admins only see a 'this console is private' note."""

    def __init__(self, args=(), **properties):
        super().__init__(**properties)
        self.admin = state.is_admin()
        self.private_box.visible = not self.admin
        self.console_box.visible = self.admin
        self._history = False
        self._paused = False
        if not self.admin:
            return
        state.heading(self.title, 1)
        state.live(self.pc_state)
        for panel in (self.waiting_panel, self.recent_panel):
            panel.add_event_handler("x-changed", self._changed)
        self._draw(state.call("console_overview"))
        self.timer.interval = 8

    def _draw(self, d):
        pc, q, n = d["pc"], d["queue"], d["counts"]
        self._paused = pc["paused"]
        state.set_attr(self.lamp, "data-state", pc["state"])
        self.pc_state.text = fmt.PC_STATE.get(pc["state"], "The PC")
        info = pc["info"] or {}
        bits = [b for b in (info.get("gpu"), info.get("model"), info.get("backend")) if b]
        if pc["state"] == "away" and pc["retry_at"]:
            left = fmt.until(pc["retry_at"]) or 0
            detail = "Asking again at %s (%s)." % (fmt.clock(pc["retry_at"]), fmt.eta(max(0, left)))
        elif pc["state"] == "offline":
            if pc["last_seen"]:
                detail = "Last seen %s. Pictures wait here until it connects." % fmt.ago(pc["last_seen"])
            else:
                detail = "Start the worker on your PC (see Connect). Pictures wait here until it's there."
        elif pc["state"] == "paused":
            detail = "Pictures keep arriving, but nothing is sent to the PC until you resume."
        else:
            detail = " · ".join(bits + ["seen " + fmt.ago(pc["last_seen"])])
        self.pc_detail.text = detail
        self.connect_link.visible = pc["state"] == "offline"
        self.pause_button.text = "Resume the queue" if pc["paused"] else "Pause the queue"
        self.pause_button.role = ["btn", "ic-play" if pc["paused"] else "ic-pause"]
        self.n_waiting.text, self.n_working.text = str(q["waiting"]), str(q["working"])
        self.n_done.text, self.n_failed.text = str(n["done"]), str(n["failed"])
        self.n_avg.text = fmt.secs(q["average_seconds"])
        if q["queue_length"]:
            self.sub.text = "%s in the queue · a picture sent now is ready %s" % (
                state.plural(q["queue_length"], "picture"), fmt.eta(q["eta_new_job_seconds"]))
        else:
            self.sub.text = "The queue is empty. A picture sent now starts straight away when the PC is there."
        waiting = [dict(j, _mode="wait") for j in d["waiting"]]
        self.waiting_panel.items = waiting
        self.no_waiting.visible = not waiting
        self.eta_note.text = "Oldest first, one at a time" if waiting else ""
        self.more_label.visible = d["more_waiting"] > 0
        self.more_label.text = "...and %d more." % d["more_waiting"]
        if not self._history:
            self._set_recent(d["recent"])
        self.events_panel.items = d["events"]
        self.no_events.visible = not d["events"]

    def _set_recent(self, rows):
        rows = [dict(j, _mode="recent") for j in rows]
        self.recent_panel.items = rows
        self.no_recent.visible = not rows

    def _reload(self, quiet=False):
        d = state.call_quiet("console_overview") if quiet else state.call("console_overview")
        if d:
            self._draw(d)

    def _changed(self, **event_args):
        self._reload()

    @handle("timer", "tick")
    def timer_tick(self, **event_args):
        self._reload(quiet=True)

    @handle("kick_button", "click")
    def kick_button_click(self, **event_args):
        r = state.call("console_kick")
        if r:
            state.toast("Asking the PC now." if r["started"] else "Nothing is waiting; the PC will be asked straight away next time.", "ok")
            self._reload()

    @handle("ping_button", "click")
    def ping_button_click(self, **event_args):
        r = state.call("console_ping")
        if r:
            res = r["result"]
            if res["online"]:
                state.toast("The PC answered%s." % (" (busy painting)" if res.get("busy") else ""), "ok")
            else:
                state.toast(res.get("error") or "The PC didn't answer.", "error")
            self._reload()

    @handle("pause_button", "click")
    def pause_button_click(self, **event_args):
        if state.call("console_pause", not self._paused):
            self._reload()

    @handle("history_button", "click")
    def history_button_click(self, **event_args):
        self._history = not self._history
        self.history_button.text = "Show the latest 12" if self._history else "Show the last 60"
        if self._history:
            d = state.call("console_history", "all", "", 60)
            self._set_recent([j for j in d["jobs"] if j["status"] not in ("queued", "working")])
        else:
            self._reload()
