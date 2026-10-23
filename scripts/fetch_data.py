"""Rebuild data/daily.csv from Binance's public archive (https://data.binance.vision).

Downloads daily `metrics` files (open-interest value) and monthly 1d klines for each symbol.
No API key needed. This is many small files (~1,700 per symbol for OI); use --start to limit.
"""
import argparse, io, os, sys, zipfile, urllib.request
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from altoi import DEFAULT_SYMBOLS

BASE = "https://data.binance.vision/data/futures/um"

def get_zip_csv(url, **kw):
    try:
        raw = urllib.request.urlopen(url, timeout=30).read()
    except Exception:
        return None
    z = zipfile.ZipFile(io.BytesIO(raw)); return pd.read_csv(z.open(z.namelist()[0]), **kw)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2021-12-01"); ap.add_argument("--end", default=None)
    ap.add_argument("--out", default="data/daily.csv")
    a = ap.parse_args()
    days = pd.date_range(a.start, a.end or pd.Timestamp.utcnow().normalize() - pd.Timedelta(days=2))
    months = sorted({d.strftime("%Y-%m") for d in days})
    oi, px = {}, {}
    for s in DEFAULT_SYMBOLS:
        for dt in days:
            ds = dt.strftime("%Y-%m-%d")
            d = get_zip_csv(f"{BASE}/daily/metrics/{s}/{s}-metrics-{ds}.zip", usecols=[0, 3])
            if d is not None and not d.dropna().empty:
                oi[(s, ds)] = float(d.dropna().iloc[-1, 1])  # last snapshot of the day
        for m in months:
            k = get_zip_csv(f"{BASE}/monthly/klines/{s}/1d/{s}-1d-{m}.zip", header=None)
            if k is None: continue
            k = k[pd.to_numeric(k[0], errors="coerce").notna()]
            for t, c in zip(k[0].astype("int64"), k[4].astype(float)):
                px[(s, pd.to_datetime(t, unit="ms").strftime("%Y-%m-%d"))] = c
        print(s, "done", file=sys.stderr)
    o = pd.Series(oi).unstack(0); p = pd.Series(px).unstack(0)
    o.index = pd.to_datetime(o.index); p.index = pd.to_datetime(p.index)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    o.sort_index().add_prefix("oi_").join(p.sort_index().add_prefix("px_"), how="outer").to_csv(a.out)

if __name__ == "__main__":
    main()
