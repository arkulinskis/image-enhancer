"""Privacy & Terms: connects the shared LegalKit page (legal-kit.js) to this app's server.

Installed from APP_MAKER/legal-kit/anvil/legal.py. Edit it there and re-run install.py.

  legal.setup(theme)   once, when the app starts (theme: {"accent": "#hex", "font": "...", ...})
  legal.refresh()      after start-up, sign-in, sign-up and sign-out: shows the reminder bar
                       to signed-in people who haven't accepted the current version, and records
                       the tick from the sign-up form
  legal.open(tab)      opens the page: "overview", "privacy", "terms" or "cookies"
  legal.consent_field()  HTML for the sign-up tick box; legal.consent_ok(dom_node) checks it
"""
import json

import anvil.server
from anvil.js import window

_state = {"ready": False}


def _kit():
    try:
        return window.LegalKit
    except Exception:
        return None


def _accept(version, source="page"):
    """Called by the page's "I agree" button (and after sign-up). Returns JSON for the page."""
    try:
        r = anvil.server.call_s("legal_accept", version, source)
    except Exception as e:
        r = {"ok": False, "error": str(e)}
    return json.dumps(r)


def setup(theme=None, mode=None, lang=None):
    k = _kit()
    if k is None:
        return
    cfg = {"theme": theme or {}}
    if mode:
        cfg["mode"] = mode
    if lang:
        cfg["lang"] = lang
    k.configure(json.dumps(cfg))
    k.setAcceptHandler(_accept)
    _state["ready"] = True


def refresh():
    """Ask the server who is signed in and what they accepted. Silent: no spinner, never raises."""
    k = _kit()
    if k is None:
        return
    if not _state["ready"]:
        setup()
    try:
        st = anvil.server.call_s("legal_state")
    except Exception:
        return
    k.setUser(json.dumps(st))


def refresh_soon():
    """refresh() without holding up the caller."""
    try:
        window.setTimeout(refresh, 50)
    except Exception:
        refresh()


def signed_out():
    k = _kit()
    if k is not None:
        k.setUser(json.dumps({"signedIn": False}))


def open(tab="overview"):
    k = _kit()
    if k is not None:
        k.open(tab)


def consent_field(class_name=""):
    k = _kit()
    return k.consentField(json.dumps({"className": class_name})) if k is not None else ""


def consent_ok(node=None, quiet=False):
    k = _kit()
    return True if k is None else bool(k.consentChecked(node, quiet))
