"""Measure a guided physical head movement through the actual local web API.

Run one phase after the person confirms they are ready. This records observed
angles/directions, not a claim of measured physical-angle ground truth.
"""
import argparse
import json
import statistics
import time
import urllib.request
from pathlib import Path


def snapshot(base,run_id,path):
    response=urllib.request.urlopen(f'{base}/object-monitor/feed?run_id={run_id}',timeout=5)
    try:
        data=b''
        while len(data)<2_000_000:
            data+=response.read(4096)
            start=data.find(b'\xff\xd8')
            end=data.find(b'\xff\xd9',start+2)
            if start>=0 and end>start:
                path.write_bytes(data[start:end+2])
                return
    finally:
        response.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['neutral','left','right','down','roll','recovery'])
    parser.add_argument('--seconds',type=float,default=7)
    parser.add_argument('--base',default='http://127.0.0.1:8000')
    args=parser.parse_args()
    output=Path(__file__).parent/'validation-output/head-pose-live'
    output.mkdir(parents=True,exist_ok=True)
    rows=[]
    start=time.monotonic()
    saved=False
    while time.monotonic()-start<args.seconds:
        state=json.load(urllib.request.urlopen(args.base+'/object-monitor/status',timeout=5))
        head=state.get('head_pose') or {}
        row=dict(elapsed=time.monotonic()-start,fps=state['fps'],head=head,
                 error=state.get('head_error'),last_alert=state.get('last_alert'))
        rows.append(row)
        if not saved and head.get('yaw') is not None and (head.get('sustained') or row['elapsed']>2):
            snapshot(args.base,state['run_id'],output/(args.phase+'.jpg'))
            saved=True
        time.sleep(.1)
    valid=[r['head'] for r in rows if r['head'].get('yaw') is not None]
    summary=dict(phase=args.phase,samples=len(rows),valid_samples=len(valid),
                 sustained_samples=sum(p['sustained'] for p in valid),
                 median_fps=statistics.median(r['fps'] for r in rows),
                 median_processing_ms=statistics.median(p['processing_ms'] for p in valid) if valid else None,
                 median_angles={axis:statistics.median(p[axis] for p in valid) for axis in ['yaw','pitch','roll']} if valid else None,
                 ranges={axis:[min(p[axis] for p in valid),max(p[axis] for p in valid)] for axis in ['yaw','pitch','roll']} if valid else None,
                 states=sorted({r['head'].get('state','unavailable') for r in rows}),
                 errors=sorted({r['error'] for r in rows if r['error']}))
    (output/(args.phase+'.json')).write_text(json.dumps(dict(summary=summary,samples=rows),indent=2))
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':
    main()
