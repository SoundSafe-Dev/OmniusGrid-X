#!/usr/bin/env python3
"""Build the OmniusGrid brand assets from the source artwork in `source/`.

Both theme variants come from ONE alpha mask which is then tinted, so the light
and dark files are pixel-identical in geometry and cannot drift apart. Editing the
outputs by hand breaks that guarantee — change `source/` and re-run instead.

    python3 docs/assets/brand/build.py

Requires Pillow. See README.md in this directory for the asset table and the
`<picture>` snippet that consumes these files.
"""
from __future__ import annotations

import os
import sys

try:
    from PIL import Image
except ImportError:  # pragma: no cover - dependency hint is the useful behaviour
    sys.exit("Pillow is required: pip install Pillow")

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "source")

# Ink colours. Light-theme ink matches GitHub's dark surface token so the lockup
# sits in the same ink as surrounding body text rather than pure black.
INK = {"light": (13, 17, 23), "dark": (255, 255, 255)}

# The wordmark's cap height is the unit everything else is expressed in.
WORDMARK_H = 300
# The mark must be TALLER than the caps or it reads small next to them; 1.42 is the
# standard optical relationship for a gear-and-text lockup at this weight.
MARK_RATIO = 1.42
GAP_RATIO = 0.30      # space between mark and wordmark, as a fraction of mark height
PAD_RATIO = 0.10      # clear space around the lockup


def mask_from(path: str, ink: str) -> Image.Image:
    """Load artwork and return an L-mode alpha mask (255 = ink), cropped to the ink.

    `ink` describes the SOURCE: "dark" for dark artwork on a light background,
    "light" for light artwork on a dark background.
    """
    grey = Image.open(path).convert("L")
    alpha = grey.point((lambda v: 255 - v) if ink == "dark" else (lambda v: v))
    # Clamp near-black and near-white so JPEG ringing and antialiasing fringe do
    # not survive as a grey halo once the mask is tinted.
    alpha = alpha.point(lambda v: 0 if v < 24 else (255 if v > 232 else v))
    box = alpha.getbbox()
    if box is None:
        raise SystemExit(f"{path}: no ink found — is the foreground/background inverted?")
    return alpha.crop(box)


def scaled(img: Image.Image, height: int) -> Image.Image:
    return img.resize((round(img.width * height / img.height), height), Image.LANCZOS)


def write(mask: Image.Image, stem: str) -> None:
    for theme, rgb in INK.items():
        out = Image.new("RGBA", mask.size, rgb + (0,))
        out.putalpha(mask)
        path = os.path.join(HERE, f"{stem}-{theme}.png")
        out.save(path, optimize=True)
        print(f"  {os.path.basename(path):36} {mask.width}x{mask.height}  "
              f"{os.path.getsize(path) // 1024}KB")


def main() -> None:
    mark = scaled(mask_from(os.path.join(SRC, "mark.png"), "dark"),
                  round(WORDMARK_H * MARK_RATIO))
    word = scaled(mask_from(os.path.join(SRC, "wordmark.png"), "light"), WORDMARK_H)

    gap = round(mark.height * GAP_RATIO)
    pad = round(mark.height * PAD_RATIO)

    lockup = Image.new("L", (pad + mark.width + gap + word.width + pad,
                             pad + mark.height + pad), 0)
    lockup.paste(mark, (pad, pad))
    # Optically centre the wordmark against the taller mark.
    lockup.paste(word, (pad + mark.width + gap, pad + (mark.height - word.height) // 2))

    print("lockup:")
    write(lockup, "omniusgrid-lockup")
    print("mark:")
    write(mark, "omniusgrid-mark")


if __name__ == "__main__":
    main()
