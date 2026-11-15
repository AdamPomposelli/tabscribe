"""Beat / downbeat accuracy vs a reference tempo map (Songscription MIDI)."""
import numpy as np, pretty_midi as pm, mir_eval


def ref_beats(midi_path, warp=None, lim=None):
    m = pm.PrettyMIDI(midi_path)
    b = m.get_beats(); d = m.get_downbeats()
    end = max(n.end for i in m.instruments for n in i.notes)
    b = b[b <= end + 0.1]; d = d[d <= end + 0.1]
    if lim: b = b[b < lim]; d = d[d < lim]
    if warp is not None: b, d = warp(b), warp(d)
    return b, d


def score(rb, rd, eb, ed, lim=None):
    eb, ed = np.asarray(eb, float), np.asarray(ed, float)
    lo, hi = rb[0] - 0.3, rb[-1] + 0.3
    eb = eb[(eb > lo) & (eb < hi)]; ed = ed[(ed > lo) & (ed < hi)]
    f = mir_eval.beat.f_measure(rb, eb, 0.07)
    cmlt, amlt = mir_eval.beat.continuity(rb, eb)[1], mir_eval.beat.continuity(rb, eb)[3]
    fd = mir_eval.beat.f_measure(rd, ed, 0.07) if len(ed) else 0.0
    # timing error of each ref beat to the nearest estimate (ms)
    err = np.array([np.min(np.abs(eb - t)) for t in rb]) * 1000 if len(eb) else np.array([999])
    return dict(F=round(f, 3), CMLt=round(cmlt, 3), AMLt=round(amlt, 3), downF=round(fd, 3),
                med_ms=round(float(np.median(err)), 1), p90_ms=round(float(np.percentile(err, 90)), 1))
