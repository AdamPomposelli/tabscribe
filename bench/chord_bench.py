"""Root agreement of bar chords vs the reference score (first 13 bars of YeuEm)."""
import sys, json, itertools
sys.path.insert(0, 'backend')
from tabscribe import harmony
REF = [['F'], ['F'], ['D'], ['C', 'F'], ['Bb'], ['F'], ['C'], ['C'], ['F'], ['F'], ['D'], ['C', 'F'], ['Bb']]

class N:
    def __init__(s, d): s.pitch, s.start, s.end = d['pitch'], d['tick'], d['end_tick']

def root(name):
    n = name.split('/')[0]
    return n[:2] if len(n) > 1 and n[1] in 'b#' else n[:1]

def score(notes, **kw):
    for k, v in kw.items(): setattr(harmony, k, v)
    ch = harmony.chords_per_bar(notes, 3840, 13, -1)
    bars = {}
    last = None
    for b in range(13):
        names = [nm for t, nm in ch if t // 3840 == b]
        bars[b] = [root(n) for n in names] or ([root(last)] if last else [])
        if names: last = names[-1]
    hit = sum(1 for b in range(13) if bars[b] and bars[b][0] == REF[b][0]) + sum(1 for b in range(13) if len(REF[b]) > 1 and len(bars[b]) > 1 and bars[b][1] == REF[b][1])
    return hit, [(b + 1, [nm for t, nm in ch if t // 3840 == b]) for b in range(13)]

def score_output(result):
    """Root agreement using the chords the pipeline actually emitted."""
    bars, last = {}, None
    for b in range(13):
        names = [c['name'] for c in result['chords'] if c['tick'] // 3840 == b]
        bars[b] = [root(n) for n in names] or ([root(last)] if last else [])
        if names: last = names[-1]
    return sum(1 for b in range(13) if bars[b] and bars[b][0] == REF[b][0]) + \
        sum(1 for b in range(13) if len(REF[b]) > 1 and len(bars[b]) > 1 and bars[b][1] == REF[b][1])


if __name__ == '__main__':
    r = json.load(open(sys.argv[1]))
    notes = [N(d) for d in r['notes']]
    print('chord roots (emitted chords):', score_output(r), '/ 15')
