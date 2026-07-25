# Brand assets

Render-ready OmniusGrid marks. The full brand spec — type scale, layout metrics,
tints, the accent law — is [`frontend/video/BRAND.md`](../../../frontend/video/BRAND.md).

| Asset | Use |
|-------|-----|
| `omniusgrid-lockup-light.png` | Mark + wordmark, ink `#0d1117`. **Light** backgrounds. |
| `omniusgrid-lockup-dark.png` | Mark + wordmark, ink `#ffffff`. **Dark** backgrounds. |
| `omniusgrid-mark-light.png` | Mark alone, dark ink. Favicons, avatars, small placements. |
| `omniusgrid-mark-dark.png` | Mark alone, white ink. |

All four are **transparent PNGs at 2× density** — 512 px tall for the lockups,
426 px for the marks — so they stay crisp on retina at the sizes actually used
(440 px and 96 px wide in the root README).

## Why two variants instead of one transparent file

A single transparent PNG only works if its ink reads on both surfaces, and this ink
does not: `#0d1117` is invisible on GitHub's dark theme and white is invisible on
light. So each theme gets its own file, selected by the viewer's own preference:

```html
<picture>
  <source media="(prefers-color-scheme: dark)"  srcset="docs/assets/brand/omniusgrid-lockup-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="docs/assets/brand/omniusgrid-lockup-light.png">
  <img src="docs/assets/brand/omniusgrid-lockup-light.png" alt="OmniusGrid" width="440">
</picture>
```

The `<img>` fallback is deliberately the **light** asset: renderers that ignore
`<picture>` overwhelmingly composite onto white.

## Regenerating

Both themes are derived from **one** alpha mask, then tinted — so the two variants
are pixel-identical in geometry and can never drift apart. Sources are the original
artwork in [`source/`](source/):

```
source/mark.png       gear mark, dark ink on white
source/wordmark.png   "OmniusGrid" wordmark, white ink on black
```

`build.py` thresholds each to an alpha mask, crops to the ink bbox, scales the mark
to 1.42× the wordmark's cap height (the standard optical relationship — matching the
heights makes the mark read small), composites with a 0.30 × mark-height gap, and
writes the tinted pairs:

```bash
python3 docs/assets/brand/build.py
```

Re-run it after replacing anything in `source/`. Do not hand-edit the outputs.
