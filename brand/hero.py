"""README lockup for Tabscribe: the app icon + "Tabscribe" set in Plus Jakarta Sans 800 as outlines.

    python3 brand/hero.py --font <PlusJakartaSans-800.woff2> --out brand/readme [--inline]

Writes hero-dark.svg / hero-light.svg (the README picks one per colour scheme), or with --inline
one SVG with #lk-icon and #lk-name (and the icon's #lk-frets) for the demo video.
"""
import argparse, os, re
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.boundsPen import BoundsPen

ap = argparse.ArgumentParser()
ap.add_argument('--font', required=True)
ap.add_argument('--out', required=True)
ap.add_argument('--inline', action='store_true')
a = ap.parse_args()

font = TTFont(a.font)
gs, cmap, hmtx = font.getGlyphSet(), font.getBestCmap(), font['hmtx']

def word(text, scale, x0, y0):
    pen, bp, x = SVGPathPen(gs), BoundsPen(gs), x0
    for ch in text:
        g = cmap[ord(ch)]
        t = (scale, 0, 0, -scale, x, y0)
        gs[g].draw(TransformPen(pen, t)); gs[g].draw(TransformPen(bp, t))
        x += hmtx[g][0] * scale - 0.025 * 1000 * scale
    return pen.getCommands(), bp.bounds

# The logo (frontend/public/logo.svg), on a 32-unit grid, drawn at 300 px.
S = 300 / 32
def icon(prefix):
    strings = ''.join(f'M{x} 3v26' for x in (12.2, 13.72, 15.24, 16.76, 18.28, 19.8))
    frets = [(9, 6.25, 10.5), (12.5, 10.75, 12.5), (7, 15.25, 15.5), (11, 19.75, 13), (10, 24.25, 10)]
    rects = ''.join(f'<rect x="{x}" y="{y}" width="{w}" height="2.5" rx="1.25"/>' for x, y, w in frets)
    return (f'<g id="{prefix}icon"><g transform="scale({S})">'
            f'<rect width="32" height="32" rx="8" fill="url(#ts-bg)"/>'
            f'<rect x="11" y="3" width="10" height="26" rx="1.5" fill="#000" fill-opacity=".2"/>'
            f'<path d="{strings}" stroke="#fff" stroke-opacity=".35" stroke-width=".6"/>'
            f'<g id="{prefix}frets" fill="#fff">{rects}</g></g></g>')

d, (x0, y0, x1, y1) = word('Tabscribe', 0.25, 360, 215)
W = x1 + 8
defs = ('<defs><linearGradient id="ts-bg" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#19c08f"/><stop offset="1" stop-color="#0a7c62"/></linearGradient></defs>')

def svg(fill, ids=False):
    p = 'lk-' if ids else 'x-'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.0f} 300" width="{W:.0f}" height="300" '
            f'fill="none" role="img" aria-label="Tabscribe">{defs}{icon(p)}'
            f'<path id="{p}name" d="{d}" fill="{fill}"/></svg>')

os.makedirs(a.out, exist_ok=True)
if a.inline:
    open(os.path.join(a.out, 'hero-inline.svg'), 'w').write(svg('#FFFFFF', True))
else:
    open(os.path.join(a.out, 'hero-dark.svg'), 'w').write(svg('#F4F4F5'))
    open(os.path.join(a.out, 'hero-light.svg'), 'w').write(svg('#0A0A0B'))
print('ok', W)
