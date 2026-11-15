# Fills index.template's slots and writes index.html.
# Needs captures/ (from capture.mjs, with captures/boxes.json) and assets/hero-inline.svg
# (python3 brand/hero.py --font <PlusJakartaSans-800.woff2> --out assets --inline).
import json, os, re

here = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(here, 'index.template')).read()
svg = open(os.path.join(here, 'assets/hero-inline.svg')).read()
svg = re.sub(r'<!--.*?-->\s*', '', svg, flags=re.S).replace('<svg ', '<svg id="lockup" ', 1)
boxes = json.load(open(os.path.join(here, 'captures/boxes.json')))

S4 = 21.05          # 100% promises
S5 = 24.05          # lockup
END = 27.6

def union(*bs):
    x, y = min(b['x'] for b in bs), min(b['y'] for b in bs)
    return {'x': x, 'y': y, 'width': max(b['x'] + b['width'] for b in bs) - x, 'height': max(b['y'] + b['height'] for b in bs) - y}

# The capo row: the "Capo" stepper line above the hint, both inside the panel.
c = boxes['capo']
boxes['capoArea'] = {'x': c['x'] - 14, 'y': c['y'] - 34, 'width': c['width'] + 36, 'height': c['height'] + 44}
boxes['soundArea'] = union(boxes['soundBtn'], boxes['soundMenu'])

def ring(id_, b, pad=8):
    return (f'<div id="{id_}" class="ring" style="left:{b["x"] - pad:.0f}px;top:{b["y"] - pad:.0f}px;'
            f'width:{b["width"] + 2 * pad:.0f}px;height:{b["height"] + 2 * pad:.0f}px"></div>')
rings = ''.join([
    ring('r-band', boxes['bandCard']), ring('r-proc', boxes['proc'], 10), ring('r-pipe', boxes['pipeline'], 10),
    ring('r-seg', boxes['seg'], 6), ring('r-capo', boxes['capoArea'], 4), ring('r-sound', boxes['soundMenu'], 6),
])

LABELS = 9
out = (src.replace('__LOCKUP__', svg).replace('__RINGS__', rings)
          .replace('__BOXES__', json.dumps(boxes)).replace('__RULER__', '<span><b></b></span>' * LABELS)
          .replace('__S1_END__', f'{S4:g}').replace('__S4__', f'{S4:g}').replace('__S5__', f'{S5:g}')
          .replace('__LOCKUP_DUR__', f'{END - S5:g}').replace('__END__', f'{END:g}'))
open(os.path.join(here, 'index.html'), 'w').write(out)
print('index.html written,', END, 's')
