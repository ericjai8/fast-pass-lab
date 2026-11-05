"""Break-and-go at major levels (PDH, PDL, overnight high/low), RTH only.
First break of each level per day: stop-order entry `buf` ATR beyond the level,
stop `stop_atr` ATR from entry. Fill bar: its far extreme (after the break) counts
as favourable; the stop is judged on its close. Flat at 15:55 ET."""
import numpy as np, pandas as pd
from data import TICK

TARGETS = (1.0, 1.5, 2.0, 3.0)

def run(S, buf=0.1, stop_atr=0.5, start=935, last_entry=1530, flat=1555, slip=1):
    o,h,l,c,atr,hm,tday = S["o"],S["h"],S["l"],S["c"],S["atr"],S["hm"],S["tday"]
    n=len(c); out=[]
    days=pd.Series(np.arange(n)).groupby(tday)
    for d, ix in days:
        ix=ix.to_numpy()
        rth=ix[(hm[ix]>=930)&(hm[ix]<1600)]
        if len(rth)<10: continue
        k0=rth[0]
        lv={"PDH":(S["pdh"][k0],1),"PDL":(S["pdl"][k0],-1),"ONH":(S["onh"][k0],1),"ONL":(S["onl"][k0],-1)}
        for name,(L,side) in lv.items():
            if not np.isfinite(L): continue
            if (side==1 and o[k0]>=L) or (side==-1 and o[k0]<=L): continue   # opened beyond: not a break
            for k in rth:
                if hm[k]<start: continue
                if hm[k]>last_entry: break
                a=atr[k-1]; trig=L+side*buf*a
                if (side==1 and h[k]>=trig) or (side==-1 and l[k]<=trig):
                    entry=(max(trig,o[k]) if side==1 else min(trig,o[k]))+side*slip*TICK
                    stop=entry-side*stop_atr*a; R=abs(entry-stop)
                    res={}; mfe=0.0; end=None
                    for j in range(k, n):
                        if hm[j]>=flat or tday[j]!=d: end=(c[j-1]-entry)*side/R; break
                        # fill bar: price broke THROUGH the level, so its far extreme came after the fill
                        # and its near extreme (toward the stop) came before -> stop judged on the close
                        adverse_px = c[j] if j==k else (l[j] if side==1 else h[j])
                        if (side==1 and adverse_px<=stop) or (side==-1 and adverse_px>=stop): end=-1.0; break
                        fav=((h[j]-entry) if side==1 else (entry-l[j]))
                        mfe=max(mfe,fav/R)
                        for t in TARGETS:
                            if t not in res and mfe>=t: res[t]=t
                    row=dict(day=d, ts=S["idx"][k], level=name, side=side, hm=hm[k], R_pts=R, mfe_R=mfe)
                    for t in TARGETS: row[f"r_{t:g}"]=res.get(t,end)
                    row["r_eod"]=end if not res or end==-1.0 else end
                    out.append(row); break
    return pd.DataFrame(out)
