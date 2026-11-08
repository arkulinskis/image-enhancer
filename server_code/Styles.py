"""The ten styles a picture can be repainted in, and how a job's instruction for the model is put together.

The prompts live in the `styles` table (seeded from DEFAULTS the first time anything asks), so the owner can tune
them on the Styles page without touching code or the PC. The PC worker gets the finished instruction with every job.
FLUX.2 [klein] (the model the worker runs in ComfyUI) follows plain edit instructions: say what to turn the picture
into, then what to keep.
"""
import anvil.server
from anvil.tables import app_tables
import anvil.tables as tables

from . import common as C

# key, label, one-line blurb (API + console), instruction for the model
DEFAULTS = [
    ("kids_book", "Kids' picture book", "Warm gouache and coloured pencil, rounded and friendly.",
     "Repaint this image as a warm children's picture-book illustration: soft gouache and coloured-pencil texture, "
     "gentle rounded shapes, friendly expressions, cosy light and a hand-painted paper grain."),
    ("scifi", "Sci-fi", "Cinematic concept art: sleek materials, glowing details, haze.",
     "Turn this image into cinematic science-fiction concept art: sleek futuristic materials, glowing panels and "
     "holographic details, atmospheric haze and dramatic rim lighting."),
    ("realistic", "Photo-realistic", "A real photograph of the same scene.",
     "Turn this illustration into a realistic photograph: real-world materials and textures, natural light and "
     "shadows, believable proportions, shallow depth of field, shot on a full-frame camera."),
    ("anime", "Anime", "Crisp line art, cel shading, painted backgrounds.",
     "Redraw this image in a clean Japanese anime style: crisp line art, cel shading with two-tone shadows, "
     "expressive eyes, vivid colours and a painted background."),
    ("watercolor", "Watercolour", "Loose washes, soft edges, paper showing through.",
     "Repaint this image as a loose watercolour painting: transparent washes, soft bleeding edges, a light pencil "
     "under-drawing and white paper showing through."),
    ("oil_painting", "Oil painting", "Classical canvas, rich glazes, visible brushwork.",
     "Repaint this image as a classical oil painting on canvas: rich layered colour, visible confident brush "
     "strokes, warm glazes and soft dramatic light."),
    ("cartoon_3d", "3D cartoon", "A still from a polished animated film.",
     "Turn this image into a still from a polished 3D animated film: soft rounded stylised forms, subsurface "
     "scattering, plush materials, warm global illumination and gentle depth of field."),
    ("comic", "Comic book", "Bold ink, halftone dots, flat punchy colour.",
     "Redraw this image as a comic-book panel: bold black ink outlines, halftone dot shading, flat saturated "
     "colours and strong contrast."),
    ("fantasy", "Fantasy art", "Painterly book-cover art with magical light.",
     "Repaint this image as epic fantasy book-cover art: painterly detail, magical glowing light, a rich storybook "
     "atmosphere and ornate textures."),
    ("claymation", "Clay stop-motion", "Plasticine figures on a miniature set.",
     "Turn this image into a handmade clay stop-motion scene: plasticine characters and props with fingerprint "
     "texture, miniature set lighting and soft shadows."),
]
DEFAULT = {k: (label, blurb, prompt) for k, label, blurb, prompt in DEFAULTS}

FIDELITY = {
    "loose": "Keep the main subjects and the overall composition, but feel free to add detail and reinterpret the background.",
    "balanced": "Keep the same subjects, composition, poses and colour scheme.",
    "strict": "Keep the exact composition, outlines, shapes, characters and colour placement; change only the rendering style.",
}


def ensure():
    """Seed the styles table once (and add any style added to DEFAULTS later)."""
    have = {r["key"] for r in app_tables.styles.search()}
    for i, (k, label, blurb, prompt) in enumerate(DEFAULTS):
        if k not in have:
            app_tables.styles.add_row(key=k, label=label, blurb=blurb, prompt=prompt, sort=i, enabled=True, updated=C.now())


def rows(enabled_only=False):
    ensure()
    out = list(app_tables.styles.search(tables.order_by("sort")))
    return [r for r in out if r["enabled"]] if enabled_only else out


def get(key):
    ensure()
    return app_tables.styles.get(key=key) if isinstance(key, str) else None


def public(r):
    return {"key": r["key"], "label": r["label"], "description": r["blurb"] or ""}


def label_of(key):
    r = get(key)
    return r["label"] if r else key


def instruction(style_row, fidelity="balanced", extra=""):
    """The finished instruction the model gets: the style, what to keep, and the caller's own words."""
    parts = [(style_row["prompt"] or "").strip(), FIDELITY.get(fidelity, FIDELITY["balanced"])]
    extra = C.text(extra, 600)
    if extra:
        parts.append(extra if extra.endswith((".", "!", "?")) else extra + ".")
    return " ".join(p for p in parts if p)


def _row(r):
    d = DEFAULT.get(r["key"])
    return {"key": r["key"], "label": r["label"], "blurb": r["blurb"] or "", "prompt": r["prompt"] or "",
            "enabled": bool(r["enabled"]), "changed": bool(d and (d[0], d[1], d[2]) != (r["label"], r["blurb"], r["prompt"])),
            "updated": C.iso(r["updated"])}


@anvil.server.callable(require_user=True)
def styles_list():
    C.require_admin()
    return {"styles": [_row(r) for r in rows()], "fidelity": FIDELITY}


@anvil.server.callable(require_user=True)
def style_save(key, label, blurb, prompt, enabled):
    C.require_admin()
    r = get(key)
    if r is None:
        return C.fail("That style no longer exists.")
    label, blurb, prompt = C.text(label, 40), C.text(blurb, 120), C.text(prompt, 1500, multiline=True)
    if len(label) < 2:
        return C.fail("Give the style a name (at least 2 characters).")
    if len(prompt) < 20:
        return C.fail("The instruction is too short to steer the model. Describe the look in a sentence or two.")
    if not enabled and len([x for x in rows(True) if x["key"] != key]) == 0:
        return C.fail("Keep at least one style switched on.")
    r.update(label=label, blurb=blurb, prompt=prompt, enabled=bool(enabled), updated=C.now())
    return C.ok(style=_row(r))


@anvil.server.callable(require_user=True)
def style_reset(key):
    C.require_admin()
    r = get(key)
    if r is None or key not in DEFAULT:
        return C.fail("That style no longer exists.")
    label, blurb, prompt = DEFAULT[key]
    r.update(label=label, blurb=blurb, prompt=prompt, updated=C.now())
    return C.ok(style=_row(r))
