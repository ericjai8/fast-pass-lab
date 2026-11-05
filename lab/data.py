"""Load NQ bars. Prices are NQ = MNQ (same index); P&L uses MNQ $2/pt."""
import json
import os

import numpy as np
import pandas as pd
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
TICK, PTV, FEE_RT = 0.25, 2.0, 1.24     # MNQ tick, $ per point per micro, round-trip fees per micro


def load(tf="5m"):
    f = {"5m": "NQ_5m_2024_2026.json", "15m": "NQ_15m_2020_2026.json"}[tf]
    a = json.load(open(os.path.join(DATA, f)))
    df = pd.DataFrame(a, columns=["ts", "open", "high", "low", "close", "volume"])
    if tf == "5m":
        rec = os.path.join(DATA, "NQ_5m_recent.csv")
        if os.path.exists(rec):
            df = pd.concat([df, pd.read_csv(rec)[["ts", "open", "high", "low", "close", "volume"]]])
    df = df.drop_duplicates("ts", keep="last").sort_values("ts")
    df.index = pd.to_datetime(df.ts, unit="s", utc=True)
    return df.drop(columns="ts")


def enrich(df, atr_len=14):
    """Common series: ATR, session VWAP, CME trading day, ET clock, daily levels."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    v = df["volume"].to_numpy(float)
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    atr = pd.Series(tr).ewm(alpha=1 / atr_len, adjust=False).mean().to_numpy()
    et = df.index.tz_convert(ET)
    tday = np.asarray((et + pd.Timedelta(hours=6)).date)
    hm = np.asarray(et.hour * 100 + et.minute)
    tp = (h + l + c) / 3
    g = pd.Series(tday)
    cv = pd.Series(v).groupby(g).cumsum().to_numpy()
    vwap = np.where(cv > 0, pd.Series(tp * v).groupby(g).cumsum().to_numpy() / np.where(cv > 0, cv, 1), tp)
    ema50 = pd.Series(c).ewm(span=50, adjust=False).mean().to_numpy()

    # daily levels per CME day: prior day high/low, overnight (6pm-9:30 ET) high/low
    d = pd.DataFrame(dict(day=tday, h=h, l=l, rth=(hm >= 930) & (hm < 1700)))
    daily = d.groupby("day").agg(dh=("h", "max"), dl=("l", "min"))
    daily["pdh"], daily["pdl"] = daily.dh.shift(1), daily.dl.shift(1)
    on = d[~d.rth].groupby("day").agg(onh=("h", "max"), onl=("l", "min"))
    daily = daily.join(on)
    pdh = daily.pdh.reindex(tday).to_numpy(); pdl = daily.pdl.reindex(tday).to_numpy()
    onh = daily.onh.reindex(tday).to_numpy(); onl = daily.onl.reindex(tday).to_numpy()
    rth = d.rth.to_numpy()
    onh = np.where(rth, onh, np.nan); onl = np.where(rth, onl, np.nan)   # overnight range only known in RTH
    return dict(o=o, h=h, l=l, c=c, v=v, atr=atr, vwap=vwap, ema50=ema50, tday=tday, hm=hm,
                pdh=pdh, pdl=pdl, onh=onh, onl=onl, idx=df.index)


def session(hm):
    if hm >= 1800 or hm < 200:
        return "Asia"
    if hm < 830:
        return "London"
    if hm < 1200:
        return "NY AM"
    return "NY PM"
