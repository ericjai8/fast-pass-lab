"""
Aggressive displacement / BOS model on 1-minute bars (the screenshot model).

Signal (same rules as tradingview/displacement.pine in amd-vp-suite):
  displacement candle: body >= 2x median body of the previous 20 candles, body >= 70%
  of its range, closes in the outer 25%.  "Bright" = that candle's CLOSE breaks the last
  confirmed swing (pivot 5 bars each side): BOS (with the 1m trend) or CHoCH (against).
Entries (both tested):
  A  at the close of the bright displacement candle (no FVG needed: can't know it yet)
  B  at the close of the NEXT candle, only if it confirms an FVG
Stop:   1 tick beyond the displacement candle's low (long) / high (short)
Target: 1.5R.  Variant: stop to breakeven once +1R.
Outcomes start on the bar after entry.  If one bar touches both stop and target, the
STOP is assumed first (conservative); those trades are counted.  Flat at 16:55 ET.
Costs: 1 tick slippage each side + $1.24 round-turn commission per MNQ = ~1.12 pts.
Control: same stop distance, same minute-of-day, random direction, random other day.
Tags: break number in the leg (1 = CHoCH / first break after a flip), C/R vs the 15m
trend (same swing logic on 15m bars, last CLOSED 15m bar), session.
"""
import glob, os, sys
import numpy as np, pandas as pd

TICK = 0.25
COST_PTS = 2 * TICK + 1.24 / 2.0           # MNQ: $2 per point -> $1.24 = 0.62 pts
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")


def load(kind="NDX"):
    files = sorted(glob.glob(os.path.join(DATA, f"{kind}_1m_*.csv.gz")))
    df = pd.concat(pd.read_csv(f, index_col=0, parse_dates=True) for f in files)
    df = df[~df.index.duplicated()].sort_index()
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df


def swing_breaks(h, l, c, p):
    """Per bar: +1 break up, -1 break down, 0 none; CHoCH flag; trend after the bar."""
    n = len(c)
    brk = np.zeros(n, np.int8); ch = np.zeros(n, bool); tr_after = np.zeros(n, np.int8)
    sh = sl = np.nan; shd = sld = True; tr = 0
    for t in range(n):
        k = t - p
        if k - p >= 0:
            w = h[k - p:t + 1]
            if h[k] == w.max() and h[k] > h[k - p:k].max():
                sh, shd = h[k], False
            w = l[k - p:t + 1]
            if l[k] == w.min() and l[k] < l[k - p:k].min():
                sl, sld = l[k], False
        if not shd and c[t] > sh:
            shd = True; brk[t] = 1; ch[t] = tr == -1; tr = 1
        if not sld and c[t] < sl:
            sld = True; brk[t] = -1; ch[t] = tr == 1; tr = -1
        tr_after[t] = tr
    return brk, ch, tr_after


def htf_trend(df, rule="15min", p=5):
    """Trend of the last CLOSED 15m bar, mapped onto 1m bars (no lookahead)."""
    r = df.resample(rule, label="left", closed="left").agg({"high": "max", "low": "min", "close": "last"}).dropna()
    _, _, tr = swing_breaks(r.high.to_numpy(), r.low.to_numpy(), r.close.to_numpy(), p)
    s = pd.Series(tr, index=r.index + pd.Timedelta(rule))      # known once the bar has closed
    return s.reindex(df.index, method="ffill").fillna(0).to_numpy()


def session(hm):
    if hm >= 1800 or hm < 300: return "Asia"
    if hm < 830: return "London"
    if hm < 1130: return "NY AM"
    if hm < 1600: return "NY PM"
    return "close"


def simulate(i_entry, d, entry, stop, h, l, c, hm, tday, tgt_r=1.5, be_at=None):
    """Returns (R before costs, ambiguous flag)."""
    R = abs(entry - stop); tgt = entry + d * tgt_r * R; stp = stop
    n = len(c)
    for j in range(i_entry + 1, n):
        if tday[j] != tday[i_entry] or (1655 <= hm[j] < 1800 and not (1655 <= hm[i_entry] < 1800)):
            return (c[j - 1] - entry) * d / R, False
        hit_s = l[j] <= stp if d == 1 else h[j] >= stp
        hit_t = h[j] >= tgt if d == 1 else l[j] <= tgt
        if hit_s:
            return (stp - entry) * d / R, hit_t
        if hit_t:
            return tgt_r, False
        if be_at is not None and stp != entry and ((h[j] - entry) * d if d == 1 else (entry - l[j])) >= be_at * R:
            stp = entry
    return (c[n - 1] - entry) * d / R, False


def run(df, piv=5, med_len=20, body_k=2.0, body_pct=0.70, close_pct=0.25):
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    et = df.index.tz_convert("America/New_York")
    hm = (et.hour * 100 + et.minute).to_numpy()
    tday = (et + pd.Timedelta(hours=6)).normalize().to_numpy()   # futures day starts 18:00 ET
    body = np.abs(c - o); rng = h - l
    med = pd.Series(body).rolling(med_len).median().shift(1).to_numpy()
    brk, ch, tr = swing_breaks(h, l, c, piv)
    tr15 = htf_trend(df)
    # break number within the leg: 1 at a flip (CHoCH or first break), +1 per same-dir BOS
    legn = np.zeros(len(c), int); cur = 0; last = 0
    for t in range(len(c)):
        if brk[t]:
            cur = cur + 1 if brk[t] == last else 1; last = brk[t]; legn[t] = cur
    rows = []
    rng_gen = np.random.default_rng(0)
    days = np.unique(tday)
    first_at = {}                                     # (day, hhmm) -> first bar index
    for k in range(len(c) - 1, -1, -1):
        first_at[(tday[k], hm[k])] = k
    for t in np.nonzero(brk)[0]:
        if t + 2 >= len(c) or not med[t] > 0 or rng[t] <= 0:
            continue
        d = int(brk[t])
        if (d == 1 and c[t] <= o[t]) or (d == -1 and c[t] >= o[t]):
            continue
        if body[t] < body_k * med[t] or body[t] / rng[t] < body_pct:
            continue
        if (d == 1 and (h[t] - c[t]) / rng[t] > close_pct) or (d == -1 and (c[t] - l[t]) / rng[t] > close_pct):
            continue
        if 1655 <= hm[t] < 1800 or tday[t + 1] != tday[t]:
            continue
        fvg = (l[t + 1] > h[t - 1]) if d == 1 else (h[t + 1] < l[t - 1])
        stop = (l[t] - TICK) if d == 1 else (h[t] + TICK)
        base = dict(ts=df.index[t], dir=d, choch=bool(ch[t]), leg=int(legn[t]), tr15=int(tr15[t]),
                    cr="C" if tr15[t] == d else "R", session=session(hm[t]), fvg=bool(fvg), year=et[t].year)
        for model, ie in (("A_close", t), ("B_fvg", t + 1)):
            if model == "B_fvg" and not fvg:
                continue
            entry = c[ie]; R = abs(entry - stop)
            if (entry - stop) * d <= 0 or R < 2 * TICK:
                continue
            for mgmt, be in (("1.5R", None), ("1.5R+BE@1R", 1.0)):
                r, amb = simulate(ie, d, entry, stop, h, l, c, hm, tday, 1.5, be)
                rows.append(dict(base, model=model, mgmt=mgmt, stop_pts=R, r_gross=r, amb=amb, r=r - COST_PTS / R))
            # control: same stop size, same minute of day, random day, random direction
            if model == "A_close":
                rd = days[rng_gen.integers(len(days))]
                k = first_at.get((rd, hm[t]))
                if k is not None:
                    dd = rng_gen.choice([-1, 1]); en = c[k]
                    r, amb = simulate(k, dd, en, en - dd * R, h, l, c, hm, tday, 1.5, None)
                    rows.append(dict(base, model="CONTROL", mgmt="1.5R", stop_pts=R, r_gross=r, amb=amb, r=r - COST_PTS / R))
    return pd.DataFrame(rows)


def summary(t, by):
    g = t.groupby(by)
    return pd.DataFrame({"n": g.size(), "win%": g.apply(lambda x: (x.r_gross >= 1.49).mean() * 100).round(1),
                         "avgR_net": g.r.mean().round(3), "sumR_net": g.r.sum().round(1),
                         "stop_pts_med": g.stop_pts.median().round(1), "ambig%": g.amb.mean().mul(100).round(1)})


if __name__ == "__main__":
    kind = sys.argv[1] if len(sys.argv) > 1 else "NDX"
    df = load(kind)
    print(kind, len(df), df.index[0], df.index[-1])
    t = run(df)
    os.makedirs(os.path.join(DATA, "..", "results"), exist_ok=True)
    t.to_csv(os.path.join(DATA, "..", "results", f"displacement_1m_{kind}.csv"), index=False)
    pd.set_option("display.width", 200)
    print("\n== all ==\n", summary(t, ["model", "mgmt"]))
    m = t[(t.mgmt == "1.5R")]
    print("\n== by year ==\n", summary(m, ["model", "year"]))
    print("\n== leg break number (1 = first break after a flip) ==\n", summary(m.assign(leg=m.leg.clip(upper=4)), ["model", "leg"]))
    print("\n== C / R vs 15m trend ==\n", summary(m, ["model", "cr"]))
    print("\n== session ==\n", summary(m, ["model", "session"]))
    print("\n== stop size buckets (pts) ==\n", summary(m.assign(sb=pd.cut(m.stop_pts, [0, 5, 10, 15, 25, 50, 1e9])), ["model", "sb"]))
