"""
Pivot Retest — limit order at a swing pivot after price moves decisively away.

  1. Swing pivot (strength 4 bars each side) confirms.
  2. Within 40 bars price moves >= 3 ATR away (ATR at the pivot) without
     trading back through the pivot first.
  3. A limit order rests AT the pivot for 25 bars. Short at pivot highs,
     long at pivot lows (fading the return to the level).
  4. Stop 0.5 ATR beyond the pivot. Entry fills 2 ticks worse than the pivot.

Pessimistic fills: if stop and target are both inside one bar, it's a loss;
the fill bar itself is checked for the stop. Every signal is evaluated
independently (overlaps allowed) for research; eval sims enforce one at a time.

For each fill we record features describing the LEVEL (strength research) and
the full path outcome for several targets (exit research).
"""
import numpy as np
import pandas as pd

from data import TICK, session

TARGETS = (1.0, 1.5, 2.0, 3.0)


def pivots(x, n, high):
    out = np.zeros(len(x), bool)
    for k in range(2 * n, len(x)):
        cn = k - n
        if high:
            out[k] = x[cn] > x[cn - n:cn].max() and x[cn] >= x[cn + 1:k + 1].max()
        else:
            out[k] = x[cn] < x[cn - n:cn].min() and x[cn] <= x[cn + 1:k + 1].min()
    return out


def run(S, piv=4, impulse=3.0, seek=40, wait=25, stop_atr=0.5, slip_ticks=2, horizon=150,
        flat_hm=1655):
    o, h, l, c, v, atr = S["o"], S["h"], S["l"], S["c"], S["v"], S["atr"]
    hm, tday = S["hm"], S["tday"]
    n = len(c)
    ph = pivots(h, piv, True)
    pl = pivots(l, piv, False)
    piv_hist = {1: [], -1: []}       # (bar, price) of earlier pivots, for prior-touch counts
    out = []
    for k in range(n):
        for side, flag in ((-1, ph[k]), (1, pl[k])):     # -1 = short at a pivot HIGH
            if not flag:
                continue
            cb = k - piv
            P = h[cb] if side == -1 else l[cb]
            a = atr[cb]
            if not np.isfinite(a) or a <= 0:
                continue
            hist = piv_hist[side]
            prior_touches = sum(1 for b, p in hist if cb - b <= 300 and abs(p - P) <= 0.25 * a)
            hist.append((cb, P))
            if len(hist) > 400:
                del hist[:200]
            # 2. impulse away
            j_imp, ext, ext_bar = None, P, cb
            for j in range(k + 1, min(n, k + 1 + seek)):
                if (side == -1 and h[j] > P) or (side == 1 and l[j] < P):
                    break                                  # reclaimed before the impulse
                if side == -1 and l[j] < ext:
                    ext, ext_bar = l[j], j
                if side == 1 and h[j] > ext:
                    ext, ext_bar = h[j], j
                if abs(P - ext) >= impulse * a:
                    j_imp = j
                    break
            if j_imp is None:
                continue
            # 3. limit at the pivot
            f = None
            for j in range(j_imp + 1, min(n, j_imp + 1 + wait)):
                if (side == -1 and h[j] >= P) or (side == 1 and l[j] <= P):
                    f = j
                    break
                if side == -1 and l[j] < ext:
                    ext, ext_bar = l[j], j
                if side == 1 and h[j] > ext:
                    ext, ext_bar = h[j], j
            if f is None:
                continue
            entry = P - side * slip_ticks * TICK            # worse fill
            stop = P - side * stop_atr * a
            R = abs(stop - entry)
            # 4. path: stop first, then targets; time exit at the horizon or the 4:55pm ET flat
            res, mfe, end_val = {}, 0.0, None
            last = min(n, f + horizon)
            for j in range(f, last):
                if j > f and flat_hm <= hm[j] < 1800 and hm[j - 1] < flat_hm:
                    end_val = (c[j - 1] - entry) * side / R
                    break
                if (side == -1 and h[j] >= stop) or (side == 1 and l[j] <= stop):
                    end_val = -1.0
                    break
                # on the fill bar only the close is known to come after the fill
                fav = ((entry - c[j]) if side == -1 else (c[j] - entry)) if j == f else \
                      ((entry - l[j]) if side == -1 else (h[j] - entry))
                mfe = max(mfe, fav / R)
                for t in TARGETS:
                    if t not in res and mfe >= t:
                        res[t] = t
            if end_val is None:
                end_val = (c[last - 1] - entry) * side / R
            row = dict(fill_bar=f, ts=S["idx"][f], side=side, level=P, entry=entry, stop=stop, R_pts=R,
                       atr=a, mfe_R=mfe, end_R=end_val)
            for t in TARGETS:
                row[f"r_{t:g}"] = res.get(t, end_val)
            # ---- level features
            vol_avg = v[max(0, cb - 20):cb].mean() if cb > 20 else np.nan
            rng = h[cb] - l[cb]
            wick = (h[cb] - max(o[cb], c[cb])) if side == -1 else (min(o[cb], c[cb]) - l[cb])
            lv = [S["pdh"][f], S["pdl"][f], S["onh"][f], S["onl"][f]]
            d_daily = min([abs(P - x) for x in lv if np.isfinite(x)] or [np.inf]) / a
            d_round100 = abs(P - round(P / 100) * 100) / a
            d_round50 = abs(P - round(P / 50) * 50) / a
            slope = S["ema50"][f] - S["ema50"][max(0, f - 12)]
            row.update(
                impulse_atr=abs(P - ext) / a,
                age_bars=f - cb,
                approach_bars=f - ext_bar,
                approach_speed=(abs(P - ext) / a) / max(1, f - ext_bar),
                prior_touches=prior_touches,
                pivot_vol=v[cb] / vol_avg if vol_avg and vol_avg > 0 else np.nan,
                pivot_wick=wick / rng if rng > 0 else 0.0,
                near_daily=d_daily,          # PDH/PDL/ONH/ONL distance in ATR
                near_round100=d_round100,
                near_round50=d_round50,
                with_trend=bool((side == -1 and slope < 0) or (side == 1 and slope > 0)),
                vs_vwap=float(np.sign(S["vwap"][f] - P) * -side),   # +1: level on the "right" side of VWAP for the fade
                session=session(hm[f]),
                day=tday[f],
                stop_pts=R,
            )
            out.append(row)
    return pd.DataFrame(out)


