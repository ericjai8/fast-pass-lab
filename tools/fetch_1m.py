"""
Download 1-minute data (runs on GitHub Actions; the research workspace has no internet).
  1. Dukascopy USATECHIDXUSD (Nasdaq-100 cash CFD) 1m bid candles, 2024-01-01 -> today
     -> data/NDX_1m_<year>.csv.gz   (UTC timestamps; volume is tick volume)
  2. Yahoo NQ=F 1m, last ~29 days (Yahoo's limit) -> data/NQ_1m_recent.csv.gz
"""
import datetime as dt, io, lzma, os, struct, sys, time
from concurrent.futures import ThreadPoolExecutor
import pandas as pd, requests

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 research"


def duka_day(d):
    url = f"https://datafeed.dukascopy.com/datafeed/USATECHIDXUSD/{d.year}/{d.month - 1:02d}/{d.day:02d}/BID_candles_min_1.bi5"
    for k in range(5):
        try:
            r = S.get(url, timeout=30)
            if r.status_code == 404 or not r.content:
                return None
            r.raise_for_status()
            raw = lzma.decompress(r.content)
            n = len(raw) // 24
            rec = struct.unpack(">" + "5if" * n, raw[:n * 24])
            a = pd.DataFrame([rec[i * 6:(i + 1) * 6] for i in range(n)], columns=["t", "open", "close", "low", "high", "volume"])
            a["ts"] = pd.Timestamp(d, tz="UTC") + pd.to_timedelta(a.t, unit="s")
            return a.drop(columns="t")
        except Exception as e:
            time.sleep(2 + 3 * k)
    print("failed", d, file=sys.stderr)
    return None


def dukascopy():
    days = pd.date_range("2024-01-01", dt.date.today() - dt.timedelta(days=1), freq="D")
    days = [d.date() for d in days if d.weekday() != 5]          # no Saturday session
    with ThreadPoolExecutor(12) as ex:
        parts = [p for p in ex.map(duka_day, days) if p is not None and len(p)]
    df = pd.concat(parts).set_index("ts").sort_index()
    df = df[df.volume > 0]                                       # drop flat filler minutes
    med = df.close.median()                                       # integer price scale -> index points
    scale = 10 ** round(__import__("math").log10(med / 20000))
    df[["open", "high", "low", "close"]] = df[["open", "high", "low", "close"]] / scale
    print("dukascopy rows", len(df), "scale", scale, df.index[0], df.index[-1], df.close.iloc[-1])
    for y, g in df.groupby(df.index.year):
        g[["open", "high", "low", "close", "volume"]].to_csv(os.path.join(OUT, f"NDX_1m_{y}.csv.gz"))


def yahoo():
    import yfinance as yf
    end = dt.datetime.utcnow(); parts = []
    for k in range(4):
        e = end - dt.timedelta(days=7 * k); s = e - dt.timedelta(days=7)
        try:
            d = yf.download("NQ=F", start=s, end=e, interval="1m", progress=False, auto_adjust=False)
            if len(d):
                d.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in d.columns]
                parts.append(d[["open", "high", "low", "close", "volume"]])
        except Exception as ex:
            print("yahoo chunk failed", k, ex, file=sys.stderr)
    if parts:
        df = pd.concat(parts); df = df[~df.index.duplicated()].sort_index()
        df.index = df.index.tz_convert("UTC"); df.index.name = "ts"
        print("yahoo rows", len(df), df.index[0], df.index[-1])
        df.to_csv(os.path.join(OUT, "NQ_1m_recent.csv.gz"))


if __name__ == "__main__":
    yahoo()
    dukascopy()
