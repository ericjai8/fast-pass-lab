"""
Liquidity grab (sweep & reclaim) at PDH / PDL / previous 4H high-low, with a
pivot-to-pivot target.

  Sweep of a HIGH: a bar trades >= 1 tick above the level; within `reclaim`
  bars (same bar included) a bar CLOSES back below it -> SHORT at that close.
  Sweep of a LOW is mirrored -> LONG.
  Stop:   1 tick beyond the sweep's extreme (the wick that took the liquidity).
  Targets: 1R, 2R, 3R, and PIVOT = the last confirmed opposite swing pivot
           (strength 4) between entry and ... i.e. the next pivot in the trade's
           direction ("pivot to pivot"). Trades whose pivot is < 1R away are
           still recorded; `pivot_R` says how far it was.
Entry is at a bar CLOSE, so outcomes start on the next bar: no intrabar guessing
about the entry. If a later bar touches both stop and target, the stop wins.
Only the first sweep of each level per day (4H levels: per 4H block).
Flat at 16:55 ET. Control: the same rules on random prices from the previous day.
"""
import numpy as np
import pandas as pd

from data import TICK, session

TARGETS = (1.0, 2.0, 3.0)


def confirmed_pivots(h, l, n=4):
    """Arrays of the most recent CONFIRMED swing high/low known at each bar."""
    N = len(h)
    last_ph = np.full(N, np.nan)
    last_pl = np.full(N, np.nan)
    cur_h = cur_l = np.nan
    for k in range(N):
        c = k - n
        if c - n >= 0:
            if h[c] > h[c - n:c].max() and h[c] >= h[c + 1:k + 1].max():
                cur_h = h[c]
            if l[c] < l[c - n:c].min() and l[c] <= l[c + 1:k + 1].min():
                cur_l = l[c]
        last_ph[k], last_pl[k] = cur_h, cur_l
    return last_ph, last_pl


def run(S, reclaim=3, max_depth_atr=1.5, slip=1, flat_hm=1655, rng_seed=0, n_random=4):
    o, h, l, c, atr, hm = S["o"], S["h"], S["l"], S["c"], S["atr"], S["hm"]
    tday = S["tday"]
    n = len(c)
    last_ph, last_pl = confirmed_pivots(h, l)
    rng = np.random.default_rng(rng_seed)
    groups = pd.Series(np.arange(n)).groupby(tday)
    keys = list(groups.groups.keys())
    rows = []

    def trade(name, L, side_of_level, bars):
        """side_of_level: +1 level is a HIGH (sweep above -> short), -1 a LOW (-> long)."""
        if not np.isfinite(L):
            return
        start = None
        for t in bars:
            swept = (h[t] >= L + TICK) if side_of_level == 1 else (l[t] <= L - TICK)
            if not swept:
                continue
            # was price on the near side before?  (a real sweep, not already through)
            if t == bars[0] or (side_of_level == 1 and c[t - 1] > L) or (side_of_level == -1 and c[t - 1] < L):
                return
            start = t
            break
        if start is None:
            return
        ext = h[start] if side_of_level == 1 else l[start]
        for t in range(start, min(start + reclaim, bars[-1] + 1)):
            ext = max(ext, h[t]) if side_of_level == 1 else min(ext, l[t])
            if abs(ext - L) > max_depth_atr * atr[start]:
                return                                      # not a grab: price ran through
            back = (c[t] < L) if side_of_level == 1 else (c[t] > L)
            if back:
                d = -side_of_level                           # trade direction
                entry = c[t] - d * slip * TICK
                stop = ext + side_of_level * TICK
                R = abs(entry - stop)
                if R <= 0:
                    return
                piv = last_pl[t] if d == -1 else last_ph[t]  # next pivot in the trade's direction
                piv_R = ((entry - piv) if d == -1 else (piv - entry)) / R if np.isfinite(piv) else np.nan
                res, end = {}, None
                tgt_piv = piv if np.isfinite(piv_R) and piv_R > 0 else None
                for j in range(t + 1, n):
                    if (flat_hm <= hm[j] < 1800 and hm[j - 1] < flat_hm) or tday[j] != tday[t]:
                        end = (c[j - 1] - entry) * d / R; break
                    if (d == 1 and l[j] <= stop) or (d == -1 and h[j] >= stop):
                        end = -1.0; break
                    fav = (h[j] - entry) if d == 1 else (entry - l[j])
                    for tt in TARGETS:
                        if tt not in res and fav >= tt * R:
                            res[tt] = tt
                    if tgt_piv is not None and "piv" not in res and fav >= piv_R * R:
                        res["piv"] = piv_R
                if end is None:
                    end = (c[n - 1] - entry) * d / R
                row = dict(level=name, ts=S["idx"][t], day=tday[t], side=d, session=session(hm[t]),
                           stop_pts=R, depth_atr=abs(ext - L) / atr[start], bars_to_reclaim=t - start,
                           pivot_R=piv_R)
                for tt in TARGETS:
                    row[f"r_{tt:g}"] = res.get(tt, end)
                row["r_piv"] = res.get("piv", end) if tgt_piv is not None else np.nan
                rows.append(row)
                return

    for i, dk in enumerate(keys):
        bars = groups.get_group(dk).to_numpy()
        if len(bars) < 20:
            continue
        k0 = bars[0]
        trade("PDH", S["pdh"][k0], 1, bars)
        trade("PDL", S["pdl"][k0], -1, bars)
        rth = bars[(hm[bars] >= 930) & (hm[bars] < 1700)]
        if len(rth) > 5:
            trade("ONH", S["onh"][rth[0]], 1, rth)
            trade("ONL", S["onl"][rth[0]], -1, rth)
        blocks = [bars[j:j + 48] for j in range(0, len(bars), 48)]
        for b in range(1, len(blocks)):
            trade("P-4H-H", h[blocks[b - 1]].max(), 1, blocks[b])
            trade("P-4H-L", l[blocks[b - 1]].min(), -1, blocks[b])
        if i > 0:
            prev = groups.get_group(keys[i - 1]).to_numpy()
            for L in c[rng.choice(prev, size=min(n_random, len(prev)), replace=False)]:
                # random level: treat as a high if it is above today's open, else a low
                trade("RANDOM", L, 1 if L > o[k0] else -1, bars)
    return pd.DataFrame(rows)
