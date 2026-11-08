"""Run the app for real in the open-source Anvil App Server (Docker) and drive it with headless Chrome.

    python -I tools/ui_test.py                 the user journey (tools/ui/flow.js), the phone-width check (phone.js), admin (admin.js),
                                               accessibility (a11y.js: axe-core WCAG 2.2 AA on every page + keyboard checks)
    python -I tools/ui_test.py --shots DIR     also screenshots of every page (desktop + phone, light + dark) into DIR
    python -I tools/ui_test.py --stop          stop the local server afterwards
    python -I tools/ui_test.py --only a11y.js  one script (flow.js, phone.js, admin.js, a11y.js or design.js)
                                               design.js = the rendered design check (APP_MAKER/design), desktop + phone:
                                               eyebrows, gradient text, invisible content, sideways scroll fail; tiny text,
                                               long lines, small touch targets, transition: all are warnings to fix

The server runs this folder's app files (no build step): container "<key>-dev" on http://localhost:<PORT>, data in the
Docker volume "<key>-data" (accounts made by tests stay there; `docker volume rm <key>-data` to start clean).
The app files are COPIED into the Docker volume "<key>-app" on every run (a Windows folder mounted into Docker made
each request take 15-60 s when Docker's file sharing was busy). Client edits apply on the next run; server-code edits
need the container restarted (--restart).
Needs Docker Desktop running and Chrome installed.
"""
import json
import pathlib
import io
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
KEY = "imageenhancer"
NAME, IMAGE = KEY + "-dev", "anvilworks/anvil-app-server:1.18.0"
PORT = 3100 + sum(map(ord, KEY)) % 800  # one port per app, so several apps can run side by side
URL = "http://localhost:%d" % PORT
UPLINK_KEY = "ie-local-test-server-uplink-key"  # the local App Server only (tools/testing/e2e_uplink.py)
AXE = pathlib.Path("C:/Users/arkvi/Documents/CLAUDE/APP_MAKER/vendor/axe-core/axe.min.js")  # a11y.js's checker


def sh(*args, check=True):
    return subprocess.run(list(args), capture_output=True, text=True, encoding="utf-8", errors="replace", check=check)


def running():
    r = sh("docker", "ps", "--filter", "name=^/%s$" % NAME, "--format", "{{.Status}}", check=False)
    return r.stdout.strip().startswith("Up")


APP_PARTS = ("anvil.yaml", ".anvil_editor.yaml", "__init__.py", "client_code", "server_code", "theme")


def copy_app():
    """Copy the files the App Server needs into the container's /apps/MainApp (the "<key>-app" volume)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for part in APP_PARTS:
            if (ROOT / part).exists():
                tar.add(str(ROOT / part), arcname=part, filter=lambda t: None if "__pycache__" in t.name else t)
    subprocess.run(["docker", "cp", "-", NAME + ":/apps/MainApp/"], input=buf.getvalue(), capture_output=True, check=True)


def start(restart=False):
    if restart:
        sh("docker", "rm", "-f", NAME, check=False)
    if not running():
        sh("docker", "rm", "-f", NAME, check=False)
        sh("docker", "volume", "rm", KEY + "-app", check=False)  # fresh copy: no files left over from old versions
        sh("docker", "create", "--name", NAME, "-p", "%d:%d" % (PORT, PORT), "-v", KEY + "-app:/apps/MainApp",
           "-v", KEY + "-data:/anvil-data", IMAGE, "--app", "MainApp", "--origin", URL,
           "--auto-migrate", "--uplink-key", UPLINK_KEY)  # new tables/columns apply to the local database (--ignore-invalid-schema would block that)
        copy_app()
        sh("docker", "start", NAME)
        print("starting the App Server ...")
    else:
        copy_app()  # client edits since the last run
    for _ in range(300):
        logs = sh("docker", "logs", NAME, check=False)
        if "Downlink client connected" in logs.stdout + logs.stderr:
            try:
                urllib.request.urlopen(URL, timeout=5).read(100)
                return
            except Exception:
                pass
        time.sleep(2)
    sys.exit("The App Server didn't start. `docker logs %s` says why." % NAME)


def drive(script, window, out, shots=(), seed=False):
    """Run a page script and/or take screenshots. shots = [(name, hash or JS expression, js to run first)]."""
    steps = [{"waitFor": "window.UI_READY === true", "timeout": 90000}]
    if script:
        code = (ROOT / "tools" / "ui" / script).read_text(encoding="utf-8")
        if "/*AXE*/" in code:
            code = code.replace("/*AXE*/", "window.__AXE_SRC = %s;" % json.dumps(AXE.read_text(encoding="utf-8")), 1)
        steps.append({"eval": code})
    if seed:
        steps.append({"eval": (ROOT / "tools" / "ui" / "seed.js").read_text(encoding="utf-8")})
    for name, where, js in shots:
        target = where if not where.startswith("#") else json.dumps(where)
        steps += [{"eval": "%s; window.__to = %s; if (location.hash !== window.__to) window.UI_READY = false; location.hash = window.__to; 1"
                           % (js or "0", target)},
                  {"waitFor": "window.UI_READY === true && location.hash === window.__to", "timeout": 30000},
                  {"wait": 1200}, {"shot": name, "full": True}]
    f = pathlib.Path(out) / ("steps-%s.json" % (script or "shots").replace(".js", ""))
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(steps), encoding="utf-8")
    env = dict(__import__("os").environ, WINDOW="1280,1000")
    if window != "1280,1000":
        env["MOBILE"] = window
    r = subprocess.run(["node", str(ROOT / "tools" / "live" / "drive.mjs"), URL + "/#landing", str(f), str(out)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=900)
    return r.stdout + r.stderr


def result(text):
    """The {ok, log} the page script returned (drive.mjs prints it after [eval])."""
    for line in text.splitlines():
        if line.startswith("[eval] {"):
            return json.loads(line[len("[eval] "):])
    return None


def main():
    args = sys.argv[1:]
    if "--stop" in args and len(args) == 1:
        sh("docker", "rm", "-f", NAME, check=False)
        return
    start(restart="--restart" in args)
    out = pathlib.Path(tempfile.mkdtemp(prefix=KEY + "-ui-"))
    failed = False
    only = args[args.index("--only") + 1] if "--only" in args else None  # e.g. --only a11y.js
    for script, window in (("flow.js", "1280,1000"), ("phone.js", "390,844"), ("admin.js", "1280,1000"), ("a11y.js", "1280,1000"),
                           ("design.js", "1280,1000"), ("design.js", "390,844")):
        if only and script != only:
            continue
        text = drive(script, window, out / (script.replace(".js", "") + ("-phone" if window.startswith("390") else "")))
        res = result(text)
        errors = [l for l in text.splitlines() if "[EXCEPTION]" in l or "Python exception" in l or "Error report" in l]
        print("==== %s (%s)" % (script, window))
        for line in (res or {}).get("log", []) or text.splitlines()[-25:]:
            print("  " + line)
        for e in errors:
            print("  " + e)
        if not res or not res.get("ok") or errors:
            failed = True
    if "--shots" in args:
        dest = pathlib.Path(args[args.index("--shots") + 1])
        guest = [("landing", "#landing"), ("auth", "#auth/signup")]
        member = [("home", "#home"), ("try", "#try"), ("keys", "#keys"), ("styles", "#styles"), ("setup", "#setup"),
                  ("job", "#job/job_demo0001"), ("profile", "#profile"), ("admin", "#admin/overview")]
        for window, tag in (("1280,1000", ""), ("390,844", "_phone")):
            for theme in ("light", "dark"):
                js = "UI.setTheme(%s)" % json.dumps(theme)
                drive(None, window, dest / (theme + tag), [(n + tag + "_" + theme, h, js) for n, h in guest])
                log = drive(None, window, dest / (theme + tag + "_in"), [(n + tag + "_" + theme, h, js) for n, h in member], seed=True)
                problems = [l for l in log.splitlines() if "TIMEOUT" in l or "EXCEPTION" in l or "error" in l.lower()]
                for p_ in problems[:5]:
                    print("  shots: " + p_[:300])
        print("screenshots in", dest)
    if "--stop" in args:
        sh("docker", "rm", "-f", NAME, check=False)
    print("ALL UI TESTS PASSED" if not failed else "UI TESTS FAILED")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
