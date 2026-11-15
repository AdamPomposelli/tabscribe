import sys, json, time
sys.path.insert(0, 'backend')
from tabscribe import rhythm
t = time.time(); b, d = rhythm.track_beats(sys.argv[1])
json.dump({"beats": b.tolist(), "downbeats": d.tolist(), "seconds": round(time.time() - t, 2)}, open(sys.argv[2], 'w'))
