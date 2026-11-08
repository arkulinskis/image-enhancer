import anvil.js
import anvil.server
from anvil import *
from anvil.js import window

from ._anvil_designer import SetupTemplate
from ... import fmt, state


class Setup(SetupTemplate):
    """#setup, Connect: setting up the PC (Uplink key, worker, ComfyUI + model), the API guide with this app's real
    address filled into the code samples, and the queue settings."""

    def __init__(self, args=(), **properties):
        super().__init__(**properties)
        state.heading(self.title, 1)
        state.live(self.pc_state)
        d = state.call("console_setup")
        self.api = d["api_base"]
        self.api_label.text = self.api
        for pre in (self.pre_py, self.pre_curl, self.pre_js, self.pre_hook):
            node = anvil.js.get_dom_node(pre)
            node.textContent = node.textContent.replace("API_BASE", self.api)
        self._pc(d["pc"])
        cfg = d["config"]
        self.retry_box.text, self.attempts_box.text, self.keep_box.text = cfg["retry_minutes"], cfg["max_attempts"], cfg["keep_days"]

    def _pc(self, pc):
        state.set_attr(self.lamp, "data-state", pc["state"])
        self.pc_state.text = fmt.PC_STATE.get(pc["state"], "The PC")
        info = pc["info"] or {}
        bits = [b for b in (info.get("gpu"), info.get("model"), info.get("backend"), info.get("version")) if b]
        if pc["last_seen"]:
            self.pc_detail.text = " · ".join(bits + ["seen " + fmt.ago(pc["last_seen"])])
        else:
            self.pc_detail.text = "Not connected yet. Follow the steps below."

    @handle("ping_button", "click")
    def ping_button_click(self, **event_args):
        r = state.call("console_ping")
        if r:
            self._pc(r["pc"])
            res = r["result"]
            state.toast("The PC answered." if res["online"] else (res.get("error") or "The PC didn't answer."),
                        "ok" if res["online"] else "error")

    @handle("copy_api", "click")
    def copy_api_click(self, **event_args):
        copied = window.IE.copy(self.api)
        state.toast("Copied." if copied else "Select the address and copy it by hand.", "ok" if copied else "error")

    @handle("save_cfg", "click")
    def save_cfg_click(self, **event_args):
        r = anvil.server.call("console_save_config", self.retry_box.text, self.attempts_box.text, self.keep_box.text)
        if not r.get("ok"):
            self.cfg_message.text, self.cfg_message.visible = r.get("error") or "That didn't work.", True
            return
        self.cfg_message.visible = False
        state.toast("Settings saved.", "ok")
