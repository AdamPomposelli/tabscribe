import sys, json, numpy as np; sys.path.insert(0,'backend'); sys.path.insert(0,'bench')
from tabscribe import chords, rhythm
from tabscribe.score import QNote
import hoa_chords as hc
from permodel import load_models
import pretty_midi as pm
P='data/projects/5edf9eeec0db'; r=json.load(open(f'{P}/result.json')); b=json.load(open(f'{P}/beats.json')); M=load_models(P)
first=min(n['time'] for n in r['notes']); last=max(n['end_time'] for n in r['notes'])
g=rhythm.build_grid(np.array(b['beats']),np.array(b['downbeats']),first,last,beats_per_bar=4)
toq=lambda ns: [QNote(-1,n.pitch,int(g.time_to_tick(n.start)),int(g.time_to_tick(n.end)),getattr(n,'velocity',1)) for n in ns if g.time_to_tick(n.start)>=-200]
ref=[type('N',(),{'pitch':n.pitch,'start':n.start,'end':n.end})() for n in pm.PrettyMIDI('bench/hoa_ref.mid').instruments[0].notes]
SRC={'muscriptor':toq(M['ms']),'reference notes':toq(ref),'vote':[QNote(i,n['pitch'],n['tick'],n['end_tick'],1) for i,n in enumerate(r['notes'])]}
def evaluate(verbose=False, **kw):
    out={}
    for k,ns in SRC.items():
        ch=chords.recognise(ns,3840,r['stats']['bars'],r['key'],4,**kw)
        a,bb,rows=hc.score({'grid':{'beats_per_bar':4},'chords':[{'tick':t,'name':n} for t,n in ch]})
        out[k]=(round(a,3),round(bb,3),rows)
    return out
if __name__=='__main__':
    o=evaluate()
    for k,(a,bb,rows) in o.items(): print(f'{k:16} root {a} family {bb}')
    if len(sys.argv)>1:
        for (i,rc,c1),(_,_,c2) in zip(o['muscriptor'][2],o['reference notes'][2]): print(f'bar {i//2+1:2}{"ab"[i%2]} ref {rc:8} ms {c1:10} refnotes {c2}')
