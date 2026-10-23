import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from altoi import dedupe_events, forward_extremes, period_stats, load_daily, run_backtest
from altoi.signal import pct_rank

DATA = os.path.join(os.path.dirname(__file__), "..", "data", "daily.csv")

def test_forward_extremes_simple():
    idx = pd.date_range("2024-01-01", periods=5)
    s = pd.Series([100, 110, 90, 120, 100], index=idx, dtype=float)
    f = forward_extremes(s, horizon=2)
    assert np.isclose(f.gain.iloc[0], 0.10) and np.isclose(f.dd.iloc[0], -0.10)
    assert f.iloc[-2:].isna().all().all()  # no look-ahead past the data end

def test_dedupe_events():
    idx = pd.date_range("2024-01-01", periods=100)
    sig = pd.Series(False, index=idx); sig.iloc[[0, 1, 5, 40, 41, 99]] = True
    ev = dedupe_events(sig, gap_days=30)
    assert list(ev.strftime("%m-%d")) == ["01-01", "02-10", "04-09"]

def test_pct_rank_no_lookahead():
    s = pd.Series(np.arange(400, dtype=float))
    r = pct_rank(s, window=365, min_periods=180)
    assert r.iloc[:179].isna().all() and r.iloc[-1] == 1.0

def test_period_stats_baseline():
    idx = pd.date_range("2024-01-01", periods=10)
    fwd = pd.DataFrame({"gain": np.linspace(0, .9, 10), "dd": -np.linspace(0, .9, 10)}, index=idx)
    o = period_stats(pd.DatetimeIndex([idx[9]]), fwd, ("2024-01-01", "2024-01-10"))
    assert o["n"] == 1 and np.isclose(o["med_dd"], -0.9) and np.isclose(o["base_med_dd"], -0.45)

def test_backtest_runs_on_bundled_data():
    res = run_backtest(load_daily(DATA)); res.pop("_series")
    for k in ("crowding", "unwind", "either"):
        assert res[k]["train"]["base_med_dd"] < 0
    assert res["crowding"]["params"] in [(p, b) for p in (.8, .9, .95) for b in (.08, .12, .15)]
