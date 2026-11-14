"""Quiet recovery when Anvil's server session has expired (APP_MAKER standard, 2026-11-14).

Anvil drops a tab's server session after a long idle spell, a laptop sleep, a network drop or a new publish. The
next server call then fails, and Anvil's default answer is a "Session expired, refresh now" box. Instead:

  1. Any uncaught SessionExpiredError reloads the page quietly at the same address (the #route stays).
  2. When the tab comes back after IDLE_MS hidden (or the window regains focus / gets a click after that long without
     one), one tiny server call (KeepAlive.session_ping) checks the session first and reloads before the person
     clicks into an error.
  3. Text typed into the page's fields is kept across that reload (sessionStorage, restored into the same fields when
     the same page opens again with the same set of fields; passwords and files never).
  Sign-in survives the reload because every sign-in uses remember=True (auth.py).

startup.py calls session_guard.start() first. A second expiry within LOOP_MS of a reload falls back to Anvil's own box
(no reload loops). Tests: window.__sg (tools/ui/session.js).
"""
import anvil
import anvil.js
import anvil.server
from anvil.js import window

IDLE_MS = 10 * 60 * 1000  # hidden / untouched this long -> check the session when the person is back
LOOP_MS = 30 * 1000       # an expiry this soon after our own reload is shown, not reloaded again
DRAFT_MS = 3 * 60 * 1000  # saved field values older than this are thrown away
KEY = "anvil.session_guard"
FIELDS = "input, textarea, select"
SKIP_TYPES = ("password", "file", "hidden", "submit", "button", "reset", "image")
_s: dict = {"on": False, "reloading": False, "away_since": 0, "last_touch": 0, "checking": False}


def _now():
    return float(window.Date.now())


def _store(name, value=None, remove=False):
    """sessionStorage get/set that never raises (private windows, blocked storage)."""
    try:
        if remove:
            window.sessionStorage.removeItem(KEY + "." + name)
        elif value is not None:
            window.sessionStorage.setItem(KEY + "." + name, value)
        else:
            return window.sessionStorage.getItem(KEY + "." + name)
    except Exception:
        return None
    return None


def is_expired(err):
    """True for Anvil's SessionExpiredError (matched by name: the validator's stubs don't have the class)."""
    name = type(err).__name__
    return name == "SessionExpiredError" or (name in ("AnvilWrappedError", "Exception")
                                             and "session" in str(err).lower() and "expired" in str(err).lower())


# ---- keep what was typed across the reload

def _fields():
    out = []
    for el in getattr(window.Array, "from")(window.document.querySelectorAll(FIELDS)):
        kind = str(el.type or "").lower()
        if kind in SKIP_TYPES or kind in ("checkbox", "radio") and not el.name:
            continue
        out.append(el)
    return out


def _label(el):
    parts = [str(el.tagName), str(el.type or "")]
    for attr in ("name", "placeholder", "aria-label", "autocomplete"):
        v = el.getAttribute(attr)
        if v:
            parts.append(str(v))
    return "|".join(parts)


def _save_fields():
    fields = _fields()
    values = []
    for i, el in enumerate(fields):
        kind = str(el.type or "").lower()
        v = bool(el.checked) if kind in ("checkbox", "radio") else str(el.value or "")
        if v not in ("", False):
            values.append([i, _label(el), v])
    if values:
        data = {"at": _now(), "hash": str(window.location.hash), "count": len(fields), "values": values}
        _store("draft", window.JSON.stringify(data))


def _restore_fields(tries=0):
    """After the reload: once the same page is open with the same fields, put the typed values back."""
    raw = _store("draft")
    if not raw:
        return
    data = window.JSON.parse(raw)
    if _now() - float(data.at) > DRAFT_MS or str(window.location.hash) != str(data.hash):
        _store("draft", remove=True)
        return
    fields = _fields()
    if not window.UI_READY or len(fields) != int(data.count):
        if tries < 40:  # the page may still be loading its data (up to ~12 s)
            window.setTimeout(lambda: _restore_fields(tries + 1), 300)
        else:
            _store("draft", remove=True)
        return
    _store("draft", remove=True)
    for item in data["values"]:
        i, label, value = int(item[0]), str(item[1]), item[2]
        el = fields[i]
        if _label(el) != label:
            continue
        if str(el.type or "").lower() in ("checkbox", "radio"):
            if bool(el.checked) != bool(value):
                el.click()
            continue
        el.value = value
        for ev in ("input", "change"):  # so Anvil's writeback and the page's own handlers see it
            el.dispatchEvent(anvil.js.new(window.Event, ev, {"bubbles": True}))


# ---- reload

def reload_page():
    """Reload at the same address, keeping typed text. Safe to call twice."""
    if _s["reloading"]:
        return
    _s["reloading"] = True
    try:
        _save_fields()
    except Exception:
        pass
    _store("reloaded", str(_now()))
    window.location.reload()


def _reloaded_recently():
    at = _store("reloaded")
    return bool(at) and _now() - float(at) < LOOP_MS


def _on_error(err):
    if is_expired(err) and not _reloaded_recently():
        reload_page()
        return
    raise err  # anything else: Anvil's usual error handling


def check_now():
    """One tiny server call; reload if the session is gone. Network trouble is left alone (the next call says so)."""
    if _s["checking"] or _s["reloading"]:
        return
    _s["checking"] = True
    try:
        anvil.server.call_s("session_ping")
    except Exception as e:
        if is_expired(e) and not _reloaded_recently():
            reload_page()
    finally:
        _s["checking"] = False
    _s["last_touch"] = _now()


def _back(event=None):
    """The person is back (tab visible, window focused or a click/key): check if they were gone long enough."""
    now = _now()
    away = _s["away_since"]
    idle = now - (_s["last_touch"] or now)
    _s["away_since"] = 0
    _s["last_touch"] = now
    if (away and now - away >= IDLE_MS) or idle >= IDLE_MS:
        check_now()


def _on_visibility(event):
    if window.document.visibilityState == "hidden":
        _s["away_since"] = _now()
    else:
        _back()


def start():
    """Call once, first thing in startup.py."""
    if _s["on"]:
        return
    _s["on"] = True
    _s["last_touch"] = _now()
    anvil.set_default_error_handling(_on_error)
    report = anvil.js.report_exceptions
    window.document.addEventListener("visibilitychange", report(_on_visibility))
    window.addEventListener("focus", report(_back))
    for ev in ("pointerdown", "keydown"):
        window.addEventListener(ev, report(_back), {"capture": True, "passive": True})
    if _store("reloaded") is not None:
        if _reloaded_recently():
            window.setTimeout(_restore_fields, 300)
        else:
            _store("reloaded", remove=True)
            _store("draft", remove=True)
    window.__sg = {"check": check_now, "idle_ms": IDLE_MS,
                   "age": lambda ms: _s.update(last_touch=_now() - float(ms))}  # tests: pretend the tab sat idle
