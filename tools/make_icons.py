"""Make the PNG app icons from theme/assets/icon.svg (headless Chrome draws them).

    python -I tools/make_icons.py [--bg "#ffffff"]

Writes theme/assets/icon-512.png (Anvil's app icon: tab, link previews, home screen; transparent corners) and
theme/assets/icon-180.png (iPhone home screen; iOS wants no transparency, so it sits on --bg, default white).
Run it again whenever icon.svg changes. The loading spinner uses icon.svg directly (web/theme.css).
"""
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ASSETS = HERE.parent / "theme" / "assets"
CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe"


def render(size, out, bg=None):
    work = pathlib.Path(tempfile.mkdtemp(prefix="icons-"))
    svg = (ASSETS / "icon.svg").read_text(encoding="utf-8")
    pad = 0 if bg is None else int(size * 0.08)
    html = ("<!doctype html><html><head><style>html,body{margin:0;width:%dpx;height:%dpx;overflow:hidden;background:%s}"
            "svg{display:block;width:%dpx;height:%dpx;margin:%dpx}</style></head><body>%s</body></html>"
            % (size, size, bg or "transparent", size - 2 * pad, size - 2 * pad, pad, svg))
    page = work / "icon.html"
    page.write_text(html, encoding="utf-8")
    shot = work / "shot.png"
    r = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                        "--default-background-color=00000000", "--window-size=%d,%d" % (size, size),
                        "--user-data-dir=" + str(work / "profile"), "--screenshot=" + str(shot), page.as_uri()],
                       capture_output=True, text=True, timeout=60)
    if not shot.exists():
        sys.exit("Chrome didn't make %s:\n%s" % (out.name, r.stderr[-800:]))
    shot.replace(out)
    print("wrote", out)


def main():
    if not (ASSETS / "icon.svg").exists():
        sys.exit("theme/assets/icon.svg is missing")
    bg = sys.argv[sys.argv.index("--bg") + 1] if "--bg" in sys.argv else "#ffffff"
    render(512, ASSETS / "icon-512.png")
    render(180, ASSETS / "icon-180.png", bg)


if __name__ == "__main__":
    main()
