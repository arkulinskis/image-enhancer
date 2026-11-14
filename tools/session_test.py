"""Expired-session test: the app must reload quietly (same page, still signed in, typed text kept) instead of
Anvil's "Session expired, refresh now" box. Runs in the local App Server like ui_test.py (start it there first or
let this script do it).

    python -I tools/session_test.py            -> SESSION TEST PASSED / FAILED

The session is "expired" by giving the browser an unknown session token and dropping its websocket: the server then
answers the next call exactly as it does for a session it has thrown away. Checks, in order:
  1. sign up (tools/ui/seed.js), open #profile, type into its first text field
  2. pretend the tab sat idle 11 minutes, expire, hide + show the tab -> the check reloads: signed in, text kept;
     again with a press anywhere instead of the tab coming back
  3. expire again (well after step 2, so not a loop), open a member page -> the uncaught error reloads quietly
  4. expire once more straight away -> no reload loop: Anvil's own box shows instead
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ui_test  # noqa: E402  (same folder)

ROOT = ui_test.ROOT
EXPIRE = ("window.anvilSessionToken = 'X' + String(window.anvilSessionToken).slice(1).split('').reverse().join('');"
          "try { window.anvilWebsocket && window.anvilWebsocket.close(); } catch (e) {} window.__mark = 1; 'expired'")
VISIBLE = ("Object.defineProperty(document, 'visibilityState', {value: '%s', configurable: true});"
           "document.dispatchEvent(new Event('visibilitychange')); 1")
TEXT = "Draft Keeper %d" % (int(time.time()) % 10000)
FIELD = ("Array.from(document.querySelectorAll('input.anvil-text-box, textarea.anvil-text-area'))"
         ".filter((i) => i.offsetParent && !i.disabled && !i.readOnly)[0]")


def steps():
    seed = (ROOT / "tools" / "ui" / "seed.js").read_text(encoding="utf-8")
    check = lambda name, cond: {"eval": "(%s) ? 'ok   %s' : 'FAIL %s'" % (cond, name, name)}  # noqa: E731
    box = "/Session Expired/i.test(document.body.innerText)"  # Anvil's own "Session Expired ... Refresh now" box
    signed_in = "document.querySelector('.anvil-role-avatar button, .ui-avatar, [data-signed-in]') || !document.querySelector('.au-card')"
    return [
        {"waitFor": "window.UI_READY === true", "timeout": 90000},
        {"eval": seed},
        {"eval": "window.UI_READY = false; location.hash = '#profile'; 1"},
        {"waitFor": "window.UI_READY === true && location.hash === '#profile' && (%s)" % FIELD, "timeout": 30000},
        {"wait": 800},
        {"eval": "(() => { const i = %s; i.focus(); i.value = %s; i.dispatchEvent(new Event('input', {bubbles: true}));"
                 " i.dispatchEvent(new Event('change', {bubbles: true})); return 'typed'; })()" % (FIELD, json.dumps(TEXT))},
        # 2. idle tab + a press -> proactive check -> quiet reload
        {"eval": "window.__sg.age(window.__sg.idle_ms + 60000); " + EXPIRE},
        {"wait": 1200},
        {"eval": VISIBLE % "hidden"},
        {"eval": VISIBLE % "visible"},
        {"waitFor": "!window.__mark && window.UI_READY === true", "timeout": 40000},
        check("tab back after a long time: reloaded the page quietly", "!window.__mark && location.hash === '#profile'"),
        {"waitFor": "(%s) && (%s).value === %s" % (FIELD, FIELD, json.dumps(TEXT)), "timeout": 15000},
        check("still signed in after the reload", signed_in),
        check("typed text kept across the reload", "(%s).value === %s" % (FIELD, json.dumps(TEXT))),
        check("no Anvil error box", "!" + box),
        # 2b. same with a press anywhere after a long idle spell (window left open, never hidden)
        {"wait": 31000},  # past the loop guard of step 2's reload
        {"eval": "window.__sg.age(window.__sg.idle_ms + 60000); " + EXPIRE},
        {"wait": 1200},
        {"eval": "document.body.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true})); 'pressed'"},
        {"waitFor": "!window.__mark && window.UI_READY === true", "timeout": 40000},
        check("first press after a long idle spell: reloaded quietly", "!window.__mark && location.hash === '#profile'"),
        # 3. uncaught SessionExpiredError (a page that calls the server) -> quiet reload
        {"wait": 31000},  # past the loop guard of the last reload
        {"eval": EXPIRE},
        {"wait": 1200},
        {"eval": "window.UI_READY = false; location.hash = '#home'; 1"},
        {"waitFor": "!window.__mark && window.UI_READY === true", "timeout": 40000},
        check("uncaught expiry reloaded quietly on the page asked for", "!window.__mark && location.hash === '#home'"),
        check("still signed in after the second reload", signed_in),
        check("no Anvil error box after the second reload", "!" + box),
        # 4. straight away again -> no loop: Anvil's own box shows (also proves the fake expiry is the real thing)
        {"eval": "window.UI_READY = false; location.hash = '#profile'; 1"},
        {"waitFor": "window.UI_READY === true && location.hash === '#profile'", "timeout": 30000},
        {"eval": EXPIRE},
        {"wait": 1200},
        {"eval": "window.UI_READY = false; location.hash = '#home'; 1"},
        {"waitFor": box, "timeout": 20000},
        check("a second expiry right after a reload does not loop (the Anvil box instead)", "window.__mark === 1 && " + box),
    ]


def main():
    ui_test.start("--restart" in sys.argv)
    out = pathlib.Path(tempfile.mkdtemp(prefix=ui_test.KEY + "-session-"))
    f = out / "steps.json"
    f.write_text(json.dumps(steps()), encoding="utf-8")
    r = subprocess.run(["node", str(ROOT / "tools" / "live" / "drive.mjs"), ui_test.URL + "/#landing", str(f), str(out)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
                       env=dict(__import__("os").environ, WINDOW="1280,1000"))
    text = r.stdout + r.stderr
    lines = [l[len("[eval] "):].strip('"') for l in text.splitlines() if l.startswith("[eval] \"ok ") or l.startswith("[eval] \"FAIL")]
    lines += [l for l in text.splitlines() if "TIMEOUT" in l or "[EXCEPTION]" in l]  # an expiry raises in the
    lines = [l for l in lines if "SessionExpired" not in l]  # console on purpose (step 4)
    for line in lines:
        print("  " + line)
    seed = [l for l in text.splitlines() if l.startswith("[eval] {")]
    if seed and "error" in seed[0]:
        print("  seed: " + seed[0][:300])
    want = len([s_ for s_ in steps() if "eval" in s_ and s_["eval"].endswith("'FAIL " + s_["eval"].split("'FAIL ")[-1])])
    good = len([l for l in lines if l.startswith("ok ")]) == want and not any(l.startswith("FAIL") or "TIMEOUT" in l for l in lines)
    print("SESSION TEST PASSED" if good else "SESSION TEST FAILED (log: %s)" % out)
    sys.exit(0 if good else 1)


if __name__ == "__main__":
    main()
