"""Core logic: features, the two signal definitions, event de-duplication and stats.

Data: one row per day, columns ``oi_<SYM>`` (open-interest value in USDT) and
``px_<SYM>`` (daily close) for Binance USDT-M perpetuals.
"""
from __future__ import annotations

import itertools
from typing import Iterable

import numpy as np
import pandas as pd

DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT",
                   "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT", "ATOMUSDT",
                   "FILUSDT", "ETCUSDT", "NEARUSDT", "UNIUSDT"]
MAJORS = ("BTCUSDT", "ETHUSDT")
HORIZON = 30
TRAIN = ("2022-01-01", "2024-06-30")
TEST = ("2024-07-01", "2026-09-11")


def load_daily(path: str, start: str = "2022-01-01") -> pd.DataFrame:
    d = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
    return d[d.index >= start].replace(0, np.nan)


def pct_rank(x: pd.Series, window: int = 365, min_periods: int = 180) -> pd.Series:
    """Rolling percentile of today's value vs. the previous values in the window (no look-ahead)."""
    return x.rolling(window, min_periods=min_periods).apply(lambda a: (a[:-1] < a[-1]).mean(), raw=True)


def forward_extremes(index_series: pd.Series, horizon: int = HORIZON) -> pd.DataFrame:
    """Max gain and max drawdown over the next ``horizon`` days (from today's close)."""
    fut = pd.concat([index_series.shift(-k) for k in range(1, horizon + 1)], axis=1)
    out = pd.DataFrame({"gain": fut.max(axis=1) / index_series - 1,
                        "dd": fut.min(axis=1) / index_series - 1}, index=index_series.index)
    out.loc[out.index > index_series.index.max() - pd.Timedelta(days=horizon)] = np.nan
    return out


def build_features(d: pd.DataFrame, symbols: Iterable[str] = DEFAULT_SYMBOLS) -> pd.DataFrame:
    alts = [s for s in symbols if s not in MAJORS]
    oi_alt = d[["oi_" + s for s in alts]].sum(axis=1, min_count=len(alts) - 1)
    oi_tot = oi_alt + d["oi_BTCUSDT"] + d["oi_ETHUSDT"]
    share = oi_alt / oi_tot
    # equal-weight altcoin index from mean daily log return
    r = np.log(d[["px_" + s for s in alts]]).diff().mean(axis=1)
    alt = np.exp(r.fillna(0).cumsum())
    btc = d["px_BTCUSDT"]
    f = pd.DataFrame(index=d.index)
    f["alt_index"] = alt
    f["alt_oi_share"] = share
    f["share_chg_rank"] = pct_rank(share - share.shift(30))
    f["btc_ret30_abs"] = (btc / btc.shift(30) - 1).abs()
    f["btc_range30"] = btc.rolling(30).max() / btc.rolling(30).min() - 1
    f["oi_minus_px30"] = np.log(oi_alt / oi_alt.shift(30)) - np.log(alt / alt.shift(30))
    f["alt_vs_90d_high"] = alt / alt.rolling(90).max()
    f["alt_oi_vs_14d_max"] = oi_alt / oi_alt.rolling(14).max() - 1
    return f


def signal_crowding(f: pd.DataFrame, p: float, b: float) -> pd.Series:
    """Signal 1: alt share of OI jumps (top percentile) while BTC is range-bound."""
    s = (f.share_chg_rank >= p) & (f.btc_ret30_abs < b) & (f.btc_range30 < b * 1.6)
    return s.fillna(False).astype(bool)


def signal_unwind(f: pd.DataFrame, near: float, gap: float, ebb: float) -> pd.Series:
    """Signal 2: alts near highs, OI recently outran price, and OI now ebbing from its 14d max."""
    s = ((f.alt_vs_90d_high >= near) & (f.oi_minus_px30.rolling(14).max() > gap)
         & (f.alt_oi_vs_14d_max <= -ebb))
    return s.fillna(False).astype(bool)


def dedupe_events(sig: pd.Series, gap_days: int = 30) -> pd.DatetimeIndex:
    """Keep the first day of each cluster; a new event needs a > gap_days quiet period."""
    ev, last = [], None
    for t in sig[sig].index:
        if last is None or (t - last).days > gap_days:
            ev.append(t)
        last = t
    return pd.DatetimeIndex(ev)


def period_stats(ev: pd.DatetimeIndex, fwd: pd.DataFrame, per: tuple[str, str]) -> dict:
    ev = ev[(ev >= per[0]) & (ev <= per[1])]
    f = fwd.loc[fwd.index.intersection(ev)].dropna()
    base = fwd.loc[per[0]:per[1]].dropna()
    o = dict(n=len(f), med_gain=f.gain.median(), med_dd=f.dd.median(), hit15=(f.dd <= -.15).mean(),
             base_med_gain=base.gain.median(), base_med_dd=base.dd.median(),
             base_hit15=(base.dd <= -.15).mean(),
             events=[(str(t.date()), round(g, 3), round(x, 3)) for t, g, x in zip(f.index, f.gain, f.dd)])
    worst_removed = sorted(o["events"], key=lambda e: e[2])[2:]
    o["med_dd_ex_worst2"] = float(np.median([e[2] for e in worst_removed])) if worst_removed else None
    return {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in o.items()}


def _score(o: dict) -> float:
    # how much deeper the median drawdown is than random days; need >= 4 events
    return -9.0 if o["n"] < 4 else o["base_med_dd"] - o["med_dd"]


GRID1 = list(itertools.product([.8, .9, .95], [.08, .12, .15]))
GRID2 = list(itertools.product([.85, .9, .95], [.1, .2, .3], [.05, .1, .15]))


def run_backtest(d: pd.DataFrame, train=TRAIN, test=TEST) -> dict:
    """Pick parameters on the train window only, then report train and out-of-sample test stats."""
    f = build_features(d)
    fwd = forward_extremes(f.alt_index)
    best = {}
    for name, grid, fn in [("crowding", GRID1, signal_crowding), ("unwind", GRID2, signal_unwind)]:
        scored = [(_score(period_stats(dedupe_events(fn(f, *p)), fwd, train)), p) for p in grid]
        best[name] = max(scored)[1]
    s1, s2 = signal_crowding(f, *best["crowding"]), signal_unwind(f, *best["unwind"])
    out = {"data_last_day": str(d.index.max().date()), "train": train, "test": test}
    for name, s in [("crowding", s1), ("unwind", s2), ("either", s1 | s2)]:
        ev = dedupe_events(s)
        out[name] = dict(params=best.get(name), train=period_stats(ev, fwd, train),
                         test=period_stats(ev, fwd, test))
    out["_series"] = dict(features=f, s1=s1, s2=s2)
    return out
