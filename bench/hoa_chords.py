"""Chord accuracy vs Songscription's chord symbols for hoadanhdanhguitar (bars 1-28, per half bar).
Transcribed from the Songscription screenshots; half bars = beats 1-2 / 3-4 of each 4/4 bar."""
import sys, json, re

REF = """F# C#/E# | D#m7 C# | B F#/A# | G#m C#11 | F# C#/E# | D#m7 C# | B C#7 | F#sus4 F# |
B A#m7 | D#m7 D#m7 | G#m7 C#7 | F#sus4 A#m7 | B A#m7 | D#m7 D#m7 | G#m7 C#7 | F#sus4 F#7 |
B A#m7 | Dm(b5) D#m7 | G#m7 G#m7 | C#sus4 C#sus4 | B C#/B | A#m7 D#m9 | G#m7 C#7 | F#sus4 A#m7 |
B C#/B | A#m7 D#m7 | G#m C#7 | F#sus4 F#sus4"""
REF_HALVES = [c for bar in REF.replace('\n', ' ').split('|') for c in bar.split()]

PC = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}

def parse(name):
    m = re.match(r'([A-G])(##|x|#|b)?(.*)$', name)
    root = PC[m.group(1)] + {'#': 1, 'b': -1, '##': 2, 'x': 2, None: 0}[m.group(2)]
    rest = m.group(3).split('/')[0]
    if rest.startswith('m') and not rest.startswith('maj'):
        fam = 'dim' if 'b5' in rest else 'min'
    elif 'sus' in rest:
        fam = 'sus'
    elif rest.startswith('dim'):
        fam = 'dim'
    elif rest.startswith('maj') or rest == '' or rest.startswith('add') or rest.startswith('6') or rest == '5':
        fam = 'maj'
    else:
        fam = 'dom'  # 7, 9, 11, 13
    return root % 12, fam

def score(result):
    g = result['grid']; bar = 960 * g['beats_per_bar']
    chords = sorted((c['tick'], c['name']) for c in result['chords'])
    root_ok = fam_ok = n = 0
    rows = []
    for i, ref in enumerate(REF_HALVES):
        t = (i // 2) * bar + (i % 2) * bar // 2 + 120
        cur = None
        for tick, name in chords:
            if tick <= t: cur = name
        n += 1
        if cur is None:
            rows.append((i, ref, '-')); continue
        r1, f1 = parse(ref); r2, f2 = parse(cur)
        root_ok += r1 == r2; fam_ok += (r1 == r2 and (f1 == f2 or {f1, f2} <= {'maj', 'dom'}))
        rows.append((i, ref, cur))
    return root_ok / n, fam_ok / n, rows

if __name__ == '__main__':
    r = json.load(open(sys.argv[1]))
    a, b, rows = score(r)
    print(f'chord root accuracy {a:.3f}   root+family {b:.3f}   ({len(rows)} half-bars)')
    if len(sys.argv) > 2:
        for i, ref, cur in rows: print(f'bar {i // 2 + 1:2} {"ab"[i % 2]}  ref {ref:8} ours {cur}')
