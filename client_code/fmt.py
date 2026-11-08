"""Small formatting helpers for the console: durations, clock times, waiting times, sizes, status words."""
import anvil.js
from anvil.js import window

STATUS = {"queued": "Waiting", "working": "On the PC", "done": "Done", "failed": "Failed", "cancelled": "Cancelled"}
PC_STATE = {"ready": "The PC is ready", "working": "The PC is painting", "away": "The PC isn't answering",
            "offline": "No PC connected yet", "paused": "The queue is paused"}


def date_of(iso):
    return anvil.js.new(window.Date, iso)


def clock(iso):
    """'14:32' (today) or '3 Nov 14:32'."""
    if not iso:
        return ""
    d = date_of(iso)
    t = d.toLocaleTimeString([], {"hour": "2-digit", "minute": "2-digit"})
    now = anvil.js.new(window.Date)
    if d.toDateString() == now.toDateString():
        return t
    return "%s %s" % (d.toLocaleDateString([], {"day": "numeric", "month": "short"}), t)


def secs(n):
    """41 -> '41 s', 130 -> '2 min 10 s', 4000 -> '1 h 7 min'."""
    if n is None:
        return ""
    n = int(round(n))
    if n < 60:
        return "%d s" % n
    if n < 3600:
        m, s = divmod(n, 60)
        return "%d min" % m if s == 0 or m >= 10 else "%d min %d s" % (m, s)
    h, rest = divmod(n, 3600)
    return "%d h %d min" % (h, rest // 60)


def eta(n):
    """Seconds until something finishes -> 'in about 3 min'."""
    if n is None:
        return "paused"
    if n < 15:
        return "any moment"
    return "in about " + secs(n if n < 60 else (n // 60) * 60)


def until(iso):
    """Seconds from now until an ISO time (negative if past)."""
    if not iso:
        return None
    return (window.Date.parse(iso) - window.Date.now()) / 1000


def ago(iso):
    if not iso:
        return "never"
    n = -until(iso)
    if n < 60:
        return "just now"
    if n < 3600:
        return "%d min ago" % (n // 60)
    if n < 86400:
        return "%d h ago" % (n // 3600)
    return clock(iso)


def size(w, h):
    return "%d×%d" % (w, h) if w and h else ""
