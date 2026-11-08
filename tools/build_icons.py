"""Write theme/assets/icons.css from the icon table in theme/assets/lh-kit.js (UI.ICONS).

    python -I tools/build_icons.py

Every icon becomes a CSS mask in the current text colour, usable two ways:
  plain HTML in a form template:   <i class="ic ic-book"></i>
  an Anvil Button or Link:         prop:role='["btn", "ic-book"]'   (the icon goes before the text)
Run it again after adding an icon to UI.ICONS.
"""
import pathlib
import re
import urllib.parse

ROOT = pathlib.Path(__file__).resolve().parent.parent
KIT = ROOT / "theme" / "assets" / "app-kit.js"
OUT = ROOT / "theme" / "assets" / "icons.css"


def main():
    text = KIT.read_text(encoding="utf-8")
    table = re.search(r"UI\.ICONS = \{(.*?)\n  \};", text, re.S).group(1)
    icons = re.findall(r"^\s*(\w+)\s*:\s*'([^']*)'", table, re.M)
    css = ["/* icons.css: made by tools/build_icons.py from UI.ICONS in app-kit.js. Don't edit by hand.",
           "   <i class=\"ic ic-NAME\"></i> in HTML, or the role ic-NAME on an Anvil Button / Link. */",
           ".ic, .anvil-role-ic > button::before, a.anvil-role-ic::before { content: \"\"; display: inline-block; width: 18px; height: 18px;",
           "  flex: none; vertical-align: -3px; background: currentColor; -webkit-mask: var(--ic) center / contain no-repeat; mask: var(--ic) center / contain no-repeat; }"]
    for name, body in icons:
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="black" stroke-width="1.9" '
               'stroke-linecap="round" stroke-linejoin="round">%s</svg>' % body.replace("currentColor", "black"))
        uri = "url(\"data:image/svg+xml,%s\")" % urllib.parse.quote(svg, safe=" =:/;,'-_.")
        css.append(".ic-%s, .anvil-role-ic-%s > button::before, a.anvil-role-ic-%s::before { --ic: %s; }" % (name, name, name, uri))
    # Roles that start with ic- also need the base rule: Anvil puts every role on the wrapper as anvil-role-<role>.
    sel = ", ".join(".anvil-role-ic-%s > button::before, a.anvil-role-ic-%s::before" % (n, n) for n, _ in icons)
    css.append(sel + " { content: \"\"; display: inline-block; width: 18px; height: 18px; flex: none; background: currentColor;"
               " -webkit-mask: var(--ic) center / contain no-repeat; mask: var(--ic) center / contain no-repeat; }")
    OUT.write_text("\n".join(css) + "\n", encoding="utf-8", newline="\n")
    print("icons.css: %d icons" % len(icons))


if __name__ == "__main__":
    main()
