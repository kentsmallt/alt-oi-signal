"""Run the backtest on data/daily.csv, write results.json and docs/chart.png."""
import argparse, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from altoi import load_daily, run_backtest

ap = argparse.ArgumentParser()
ap.add_argument("--data", default="data/daily.csv")
ap.add_argument("--out", default="results.json")
ap.add_argument("--chart", default="docs/chart.png")
a = ap.parse_args()

res = run_backtest(load_daily(a.data))
ser = res.pop("_series")
json.dump(res, open(a.out, "w"), indent=1, default=float)
for k in ("crowding", "unwind", "either"):
    for p in ("train", "test"):
        s = res[k][p]
        fmt = lambda v: "n/a" if v is None else f"{v:+.1%}"
        print(f"{k:9s} {p:5s} n={s['n']:2d}  med 30d max DD {fmt(s['med_dd'])} (random {fmt(s['base_med_dd'])})"
              f"  med 30d max gain {fmt(s['med_gain'])} (random {fmt(s['base_med_gain'])})")
if a.chart:
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    os.makedirs(os.path.dirname(a.chart) or ".", exist_ok=True)
    f = ser["features"]; fig, ax = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
    ax[0].plot(f.index, f.alt_index, lw=1, color="k"); ax[0].set_yscale("log"); ax[0].set_title("Equal-weight altcoin index (15 alts) with signal days")
    for s, c, lab in [(ser["s1"], "tab:orange", "crowding"), (ser["s2"], "tab:red", "unwind")]:
        ax[0].scatter(f.index[s], f.alt_index[s], s=12, color=c, label=lab, zorder=3)
    ax[0].axvline(pd_t := __import__("pandas").Timestamp(res["test"][0]), ls="--", color="gray"); ax[0].legend()
    ax[1].plot(f.index, f.alt_oi_share, lw=1); ax[1].set_title("Altcoin share of total open interest (alts / alts+BTC+ETH)")
    ax[1].axvline(pd_t, ls="--", color="gray"); fig.tight_layout(); fig.savefig(a.chart, dpi=110)
    print("chart ->", a.chart)
