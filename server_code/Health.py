"""PC health: when the PC was there (10-minute slots, 8 days kept), what it made, how fast, and what went wrong.

app_settings["pc_uptime"] = {"YYYY-MM-DDTHH" (UTC hour): bitmask of the six 10-minute slots the PC was seen in}.
Worker.py marks the current slot whenever the PC says hello (every 2 minutes), answers "Check the PC" or finishes a
job, so a running worker fills every slot. Nothing is recorded before this feature shipped: the page says
"since <first slot>" and counts uptime only from then.
"""
import datetime as dt

from anvil.tables import app_tables
import anvil.tables.query as q

from . import common as C
from . import Diagnose, Queue, Styles

KEY = "pc_uptime"
KEEP_HOURS = 8 * 24
SLOTS = 6


def _hour_key(t):
    return t.strftime("%Y-%m-%dT%H")


def _parse_hour(k):
    try:
        return dt.datetime.strptime(k, "%Y-%m-%dT%H").replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def mark_up(t=None):
    """The PC was seen now: set this 10-minute slot's bit (one small app_settings write)."""
    t = t or C.now()
    up = dict(C.get_setting(KEY, {}) or {})
    k = _hour_key(t)
    bit = 1 << min(SLOTS - 1, t.minute // 10)
    if int(up.get(k) or 0) & bit:
        return
    up[k] = int(up.get(k) or 0) | bit
    cutoff = _hour_key(t - dt.timedelta(hours=KEEP_HOURS))
    up = {key: v for key, v in up.items() if key >= cutoff}
    C.set_setting(KEY, up)


def _slots(mask):
    return bin(int(mask or 0)).count("1")


def report(tz_minutes=0):
    """Everything the Health page shows. tz_minutes = the browser's offset from UTC (so days are the owner's days)."""
    try:
        off = dt.timedelta(minutes=max(-840, min(840, int(tz_minutes or 0))))
    except (TypeError, ValueError):
        off = dt.timedelta(0)
    now = C.now()
    up = C.get_setting(KEY, {}) or {}
    hours = sorted(h for h in (_parse_hour(k) for k in up) if h)
    first = hours[0] if hours else None
    local_now = now + off
    day0 = (local_now - dt.timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = day0 - off
    jobs = [j for j in app_tables.jobs.search(finished=q.greater_than(start_utc)) if not j["is_demo"]]
    by_hour: dict = {}
    for j in jobs:
        if j["status"] not in ("done", "failed"):
            continue
        k = _hour_key(j["finished"].astimezone(dt.timezone.utc))
        cell = by_hour.setdefault(k, [0, 0, 0.0])
        if j["status"] == "done":
            cell[0] += 1
            cell[2] += float(j["seconds"] or 0)
        else:
            cell[1] += 1

    days, seen_slots, possible_slots = [], [], []      # per-slot list (True/False) over the known range, for gaps
    up24 = [0, 0]
    for d in range(7):
        local_day = day0 + dt.timedelta(days=d)
        cells = []
        tot = {"up": 0, "possible": 0, "done": 0, "failed": 0, "secs": 0.0}
        for hr in range(24):
            h_utc = local_day + dt.timedelta(hours=hr) - off
            k = _hour_key(h_utc)
            n = by_hour.get(k, [0, 0, 0.0])
            if h_utc > now:
                cells.append({"state": "future", "done": 0, "failed": 0})
                continue
            possible = SLOTS if h_utc + dt.timedelta(hours=1) <= now else (now.minute // 10 + 1)
            known = first is not None and h_utc >= first
            got = _slots(up.get(k)) if known else 0
            if known:
                tot["up"] += got
                tot["possible"] += possible
                mask = int(up.get(k) or 0)
                for s in range(possible):
                    seen_slots.append(bool(mask & (1 << s)))
                if now - h_utc < dt.timedelta(hours=24):
                    up24[0] += got
                    up24[1] += possible
            tot["done"] += n[0]
            tot["failed"] += n[1]
            tot["secs"] += n[2]
            cells.append({"state": "known" if known else "unknown", "up": round(got / float(possible), 2) if known else None,
                          "done": n[0], "failed": n[1], "hour": hr})
        days.append({"label": local_day.strftime("%a %d %b").replace(" 0", " "), "cells": cells,
                     "uptime": round(100.0 * tot["up"] / tot["possible"]) if tot["possible"] else None,
                     "done": tot["done"], "failed": tot["failed"],
                     "avg": round(tot["secs"] / tot["done"], 1) if tot["done"] else None})

    longest, run = 0, 0
    for s in seen_slots:
        run = 0 if s else run + 1
        longest = max(longest, run)
    done7 = [j for j in jobs if j["status"] == "done"]
    failed7 = [j for j in jobs if j["status"] == "failed"]
    styles: dict = {}
    for j in done7 + failed7:
        s = styles.setdefault(j["style"], {"key": j["style"], "label": Styles.label_of(j["style"]), "done": 0, "failed": 0, "secs": 0.0})
        if j["status"] == "done":
            s["done"] += 1
            s["secs"] += float(j["seconds"] or 0)
        else:
            s["failed"] += 1
    style_rows = []
    for s in sorted(styles.values(), key=lambda x: -(x["done"] + x["failed"])):
        style_rows.append({"label": s["label"], "done": s["done"], "failed": s["failed"],
                           "avg": round(s["secs"] / s["done"], 1) if s["done"] else None})
    day_ago = now - dt.timedelta(hours=24)
    seen = Queue.pc_seen()
    total7 = len(done7) + len(failed7)
    return {
        "days": days,
        "since": C.iso(first),
        "uptime_24": round(100.0 * up24[0] / up24[1]) if up24[1] else None,
        "uptime_7": round(100.0 * len([s for s in seen_slots if s]) / len(seen_slots)) if seen_slots else None,
        "longest_gap_minutes": longest * 10,
        "done_24": len([j for j in done7 if j["finished"] > day_ago]),
        "done_7": len(done7), "failed_7": len(failed7),
        "fail_rate_7": round(100.0 * len(failed7) / total7) if total7 else None,
        "avg_7": round(sum(float(j["seconds"] or 0) for j in done7) / len(done7), 1) if done7 else None,
        "styles": style_rows,
        "problems": Diagnose.problems(7),
        "worker": seen.get("info") or {}, "last_seen": seen.get("last_seen"),
    }
