"""
SpacemanBTC "Key Levels" (IDWM) rebuilt from bars, plus a hold-vs-break study.

Levels (per CME trading day, 6pm ET start):
  Daily:     DO, PDH, PDL, PDM            Weekly:    WO, PWH, PWL, PWM
  Monthly:   MO, PMH, PML, PMM            Quarterly: QO, PQH, PQL, PQM
  Yearly:    YO                           Monday:    MDAY-H, MDAY-L, MDAY-M (Tue-Fri)
  4H:        4H-O, P-4H-H, P-4H-L, P-4H-M (4-hour blocks from 6pm ET)
  RANDOM:    control levels = closes of random bars from the previous day

Touch study: the first bar each day (or 4H block) whose range contains the level,
approaching from one side. From the NEXT bar on: HOLD if price moves k*ATR back
to the approach side first, BREAK if it moves k*ATR through first. A bar that
does both is AMBIGUOUS (excluded). No result by the end of the day = NONE.
"""
import numpy as np
import pandas as pd

from data import session


def build_levels(S, df):
    et = S["idx"].tz_convert("America/New_York")
    tday = pd.to_datetime(pd.Series(S["tday"]))
    d = pd.DataFrame(dict(day=tday, o=S["o"], h=S["h"], l=S["l"], c=S["c"]))
    daily = d.groupby("day").agg(o=("o", "first"), h=("h", "max"), l=("l", "min"))
    out = {}
    out["DO"] = daily.o
    out["PDH"], out["PDL"] = daily.h.shift(1), daily.l.shift(1)
    out["PDM"] = (out["PDH"] + out["PDL"]) / 2

    def period(key, o_name, prefix):
        g = daily.groupby(key)
        agg = g.agg(o=("o", "first"), h=("h", "max"), l=("l", "min"))
        prev = agg.shift(1)
        k = key(daily.index) if callable(key) else key
        out[o_name] = pd.Series(agg.o.reindex(k).to_numpy(), index=daily.index)
        if prefix:
            out[prefix + "H"] = pd.Series(prev.h.reindex(k).to_numpy(), index=daily.index)
            out[prefix + "L"] = pd.Series(prev.l.reindex(k).to_numpy(), index=daily.index)
            out[prefix + "M"] = (out[prefix + "H"] + out[prefix + "L"]) / 2

    wk = daily.index.to_period("W-SUN")       # CME week: Monday trading day .. Friday
    mo = daily.index.to_period("M")
    qt = daily.index.to_period("Q")
    yr = daily.index.to_period("Y")
    for key, oname, pre in ((wk, "WO", "PW"), (mo, "MO", "PM"), (qt, "QO", "PQ"), (yr, "YO", None)):
        agg = daily.groupby(key).agg(o=("o", "first"), h=("h", "max"), l=("l", "min"))
        prev = agg.shift(1)
        out[oname] = pd.Series(agg.o.reindex(key).to_numpy(), index=daily.index)
        if pre:
            out[pre + "H"] = pd.Series(prev.h.reindex(key).to_numpy(), index=daily.index)
            out[pre + "L"] = pd.Series(prev.l.reindex(key).to_numpy(), index=daily.index)
            out[pre + "M"] = (out[pre + "H"] + out[pre + "L"]) / 2
    # Monday range, active Tue-Fri of the same week
    mon = daily[daily.index.dayofweek == 0]
    mh = pd.Series(mon.h.to_numpy(), index=mon.index.to_period("W-SUN"))
    ml = pd.Series(mon.l.to_numpy(), index=mon.index.to_period("W-SUN"))
    active = daily.index.dayofweek > 0
    out["MDAY-H"] = pd.Series(np.where(active, mh.reindex(wk).to_numpy(), np.nan), index=daily.index)
    out["MDAY-L"] = pd.Series(np.where(active, ml.reindex(wk).to_numpy(), np.nan), index=daily.index)
    out["MDAY-M"] = (out["MDAY-H"] + out["MDAY-L"]) / 2
    return pd.DataFrame(out)


def touches(S, levels_by_day, k=1.0, rng_seed=0, n_random=4):
    h, l, c, atr, hm = S["h"], S["l"], S["c"], S["atr"], S["hm"]
    tday = pd.to_datetime(pd.Series(S["tday"])).to_numpy()
    idx = S["idx"]
    rng = np.random.default_rng(rng_seed)
    days = pd.Series(np.arange(len(c))).groupby(tday)
    day_list = list(days.groups.keys())
    rows = []

    def study(name, L, bars):
        if not np.isfinite(L) or len(bars) < 3:
            return
        for t in bars[1:]:
            if l[t] <= L <= h[t] and c[t - 1] != L:
                s = 1 if L > c[t - 1] else -1     # +1: level above price (resistance), -1: support
                a = atr[t]
                res = "NONE"
                for j in bars[bars > t]:
                    back = (l[j] <= L - k * a) if s == 1 else (h[j] >= L + k * a)
                    thru = (h[j] >= L + k * a) if s == 1 else (l[j] <= L - k * a)
                    if back and thru:
                        res = "AMBIG"; break
                    if back:
                        res = "HOLD"; break
                    if thru:
                        res = "BREAK"; break
                rows.append(dict(level=name, ts=idx[t], day=tday[t], approach="from below" if s == 1 else "from above",
                                 session=session(hm[t]), result=res))
                return

    for i, dkey in enumerate(day_list):
        bars = days.get_group(dkey).to_numpy()
        if dkey not in levels_by_day.index:
            continue
        row = levels_by_day.loc[dkey]
        for name, L in row.items():
            study(name, L, bars)
        # random control levels: closes of random bars from the previous day
        if i > 0:
            prev = days.get_group(day_list[i - 1]).to_numpy()
            for L in c[rng.choice(prev, size=min(n_random, len(prev)), replace=False)]:
                study("RANDOM", L, bars)
        # 4H levels: blocks of 48 five-minute bars from the 6pm ET open
        blocks = [bars[j:j + 48] for j in range(0, len(bars), 48)]
        for b_i in range(1, len(blocks)):
            pb, cb = blocks[b_i - 1], blocks[b_i]
            ph_, pl_ = h[pb].max(), l[pb].min()
            for name, L in (("4H-O", S["o"][cb[0]]), ("P-4H-H", ph_), ("P-4H-L", pl_), ("P-4H-M", (ph_ + pl_) / 2)):
                study(name, L, cb)
    return pd.DataFrame(rows)
