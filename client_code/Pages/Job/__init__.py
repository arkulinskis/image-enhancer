from anvil import *
import anvil.server

from ._anvil_designer import JobTemplate
from ... import fmt, router, state


class Job(JobTemplate):
    """#job/<job id>: one picture, before and after, with everything known about it. Watches the job every 4 s
    while it's still waiting or on the PC."""

    def __init__(self, args=(), **properties):
        super().__init__(**properties)
        self.job_id = args[0] if args else ""
        state.heading(self.title, 1)
        state.live(self.state_note)
        self._load(anvil.server.call("console_job", self.job_id))

    def _load(self, r):
        if not r or not r.get("ok"):
            self.missing.visible, self.body.visible = True, False
            self.missing_text.text = (r or {}).get("error") or "It may have been deleted."
            self.status.visible = False
            self.timer.interval = 0
            return
        self.missing.visible, self.body.visible = False, True
        j = self.j = r["job"]
        self.title.text = j["style_label"]
        self.sub.text = j["id"]
        self.status.visible = True
        self.status.text = fmt.STATUS.get(j["status"], j["status"])
        self.status.role = ["st", "st-" + j["status"]]
        self.compare.before_url = j["source_url"] or ""
        self.compare.after_url = j["result_url"] or ""
        open_ = j["status"] in ("queued", "working")
        if j["status"] == "working":
            note = "The PC is painting this one now. Ready %s." % fmt.eta(j["eta_seconds"])
        elif j["status"] == "queued":
            if j.get("next_try_at") and (fmt.until(j["next_try_at"]) or 0) > 0:
                note = "Waiting: number %s in the queue, next try at %s." % (j["position"], fmt.clock(j["next_try_at"]))
            else:
                note = "Waiting: number %s in the queue, ready %s." % (j["position"], fmt.eta(j["eta_seconds"]))
        else:
            note = ""
        self.state_note.text, self.state_note.visible = note, bool(note)
        self.error_note.text = j["error"] or ""
        self.error_note.visible = bool(j["error"])
        self.download_link.visible = bool(j["result_url"])
        if j["result_url"]:
            state.set_attr(self.download_link, "href", j["result_url"])
        self.next_button.visible = j["status"] == "queued" and (j["position"] or 0) > 1
        self.cancel_button.visible = j["status"] == "queued"
        self.retry_button.visible = j["status"] in ("failed", "cancelled") and not j["demo"]
        self.delete_button.visible = j["status"] != "working"
        self.f_style.text = j["style_label"]
        self.f_app.text = j["app"] + (" (demo)" if j["demo"] and "demo" not in j["app"].lower() else "")
        self.f_ref.text = j["ref"] or "-"
        self.f_sent.text = fmt.clock(j["created"])
        self.f_done.text = ("%s, %s" % (fmt.clock(j["finished"]), fmt.secs(j["seconds"]))) if j["finished"] and j["seconds"] else (
            fmt.clock(j["finished"]) if j["finished"] else "-")
        sent = fmt.size(j["width"], j["height"])
        made = fmt.size(j["result_width"], j["result_height"])
        self.f_size.text = (sent + (" -> " + made if made else "")) or "-"
        self.f_opts.text = "%s · %s MP · %s · size %s%s" % (j["fidelity"], j["megapixels"], j["format"], j["size"],
                                                              (" · seed %s" % j["seed"]) if j["seed"] is not None else "")
        self.f_tries.text = str(j["attempts"])
        w = j["worker"] or {}
        self.f_pc.text = " · ".join([str(x) for x in (w.get("model"), w.get("backend"), w.get("gpu")) if x]) or "-"
        hook = j.get("callback")
        self.f_hook.text = ("%s (%s)" % (hook["url"], hook["status"] or "not sent yet")) if hook else "none"
        self.instr.text = j["instruction"] or "-"
        self.timer.interval = 4 if open_ else 0

    @handle("timer", "tick")
    def timer_tick(self, **event_args):
        r = state.call_quiet("console_job", self.job_id)
        if r:
            self._load(r)

    def _act(self, fn, done_msg):
        r = state.call(fn, self.job_id)
        if r:
            state.toast(done_msg, "ok")
            self._load(anvil.server.call("console_job", self.job_id))

    @handle("next_button", "click")
    def next_button_click(self, **event_args):
        self._act("console_next", "Moved to the front of the queue.")

    @handle("retry_button", "click")
    def retry_button_click(self, **event_args):
        self._act("console_retry", "Back in the queue.")

    @handle("cancel_button", "click")
    def cancel_button_click(self, **event_args):
        if confirm("The app that sent it will see it as cancelled.", title="Cancel this picture?",
                   buttons=[("Keep it", False), ("Cancel it", True)], role="app-dialog"):
            self._act("console_cancel", "Cancelled.")

    @handle("delete_button", "click")
    def delete_button_click(self, **event_args):
        if confirm("The picture, the result and their links are deleted. The app that sent it can't fetch it any more.",
                   title="Delete this job?", buttons=[("Keep it", False), ("Delete", True)], role="app-dialog"):
            if state.call("console_delete", self.job_id):
                state.toast("Deleted.", "ok")
                router.go("home")
