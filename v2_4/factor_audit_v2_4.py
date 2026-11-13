"""V2.4 retrospective volume-factor audit; read-only V2.1/V2.2 engines.

No optimized strategy, real-market alpha claim, or point-in-time certification.
See README.md for units, attribution, static controls and data limitations.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata as md
import json
import platform
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for folder in ("v2_1", "v2_2"):
    sys.path.insert(0, str(ROOT / folder))
from backtest_v2_1 import (TICKERS, _validate_frame, monthly_schedule,
                          preprocess_factors, demo_data)
from backtest_v2_2 import make_targets, simulate_account, save_account

BASE_COMMIT = "428a1ea425e75d24939310b2f84b701826ee7067"
ENGINE_BLOBS = {"v2_1/backtest_v2_1.py": "b940174681ed6527fb8624c06727b768a288bf83",
                "v2_2/backtest_v2_2.py": "fcc5dc2514791d1f131c3f2631f00e87378f4bf1"}


def verify_engines() -> None:
    for name, expected in ENGINE_BLOBS.items():
        b = (ROOT / name).read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(b)).encode() + b"\0" + b).hexdigest()
        if actual != expected:
            raise ValueError(f"Inherited engine changed: {name}; audit source before running.")


@dataclass
class Data:
    close: pd.DataFrame
    volume: pd.DataFrame
    source_close: pd.DataFrame | None = None
    splits: pd.DataFrame | None = None


def validate(data: Data) -> None:
    # Deliberately strict: do not drop bad stocks using future data availability.
    for name in ("close", "volume", "source_close", "splits"):
        f = getattr(data, name)
        if f is None:
            continue
        _validate_frame(f, name)
        if not f.index.equals(data.close.index) or not f.columns.equals(data.close.columns):
            raise ValueError(f"{name}: dates/ticker order must match close exactly")
        if not np.isfinite(f.to_numpy()).all():
            raise ValueError(f"{name}: missing/nonfinite observations; no filling or dropping")
        if (f < 0).any().any() or (name in ("close", "source_close") and (f == 0).any().any()):
            raise ValueError(f"{name}: invalid price, volume or split value")
    monthly_schedule(data.close.index)


def read_data(folder: Path) -> Data:
    def read(name: str, required: bool = False):
        path = folder / f"{name}.csv"
        if not path.exists() and not required:
            return None
        return pd.read_csv(path, index_col=0, parse_dates=True)
    return Data(read("close", True), read("volume", True), read("source_close"), read("splits"))


def download(start: str, end: str) -> Data:
    """Unverified network adapter. Yahoo Close is NOT assumed as-traded raw price."""
    import yfinance as yf
    d = yf.download(TICKERS, start=start, end=end, auto_adjust=False, actions=True,
                    progress=False, threads=False, keepna=True, group_by="column",
                    multi_level_index=True)
    def field(name: str) -> pd.DataFrame:
        if d is None or d.empty or name not in d.columns.get_level_values(0):
            raise ValueError(f"Yahoo response missing {name}; no substitution allowed")
        f = d[name].reindex(columns=TICKERS).copy()
        f.index = pd.DatetimeIndex(f.index).tz_localize(None).normalize()
        return f.sort_index()
    # Adj Close matches the accounting convention of earlier auto_adjust=True.
    # Close * Volume is labelled a provider-basis dollar-activity PROXY.
    return Data(field("Adj Close"), field("Volume"), field("Close"), field("Stock Splits"))


def volume_score(volume: pd.DataFrame) -> pd.DataFrame:
    raw = np.log1p(volume.rolling(20, min_periods=20).mean())
    return preprocess_factors({"v": raw})["v"]


def score_account(close, score, n=10, cost_bps=10., initial=1e6):
    targets, logs, schedule = make_targets(close, score, n_stocks=n)
    r = simulate_account(close, targets["portfolio"], initial, cost_bps)
    r.decisions, r.schedule = logs["portfolio"], schedule
    return r


def static_controls(close, dynamic, cost_bps=10., initial=1e6):
    """Freeze names on first executable valid signal, never on a future top list."""
    valid = dynamic.decisions.query("status == 'target_scheduled'")
    if valid.empty:
        raise ValueError("No executable signal; need enough sessions and eligible stocks")
    anchor = valid.iloc[0]
    names = str(anchor.selected).split("|")
    targets = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    for d in dynamic.schedule.execution_date:
        if d >= anchor.execution_date:
            targets.loc[d] = 0.
            targets.loc[d, names] = 1. / len(names)
    once = targets * np.nan
    once.loc[anchor.execution_date] = targets.loc[anchor.execution_date]
    return {"static_monthly": simulate_account(close, targets, initial, cost_bps),
            "static_buy_hold": simulate_account(close, once, initial, cost_bps)}, {
                "signal_date": str(anchor.signal_date), "execution_date": str(anchor.execution_date),
                "names": names, "rule": "first valid signal, frozen thereafter"}


def attribution(close, account):
    """Exact additive P&L / initial capital, NOT additive CAGR or causal alpha."""
    prev_units = account.units_after_close.shift(1, fill_value=0.)
    market = prev_units * close.diff().fillna(0.)
    fees = pd.DataFrame(0., index=close.index, columns=close.columns)
    if not account.trades.empty:
        fees = account.trades.pivot_table(index="date", columns="ticker", values="fee", aggfunc="sum")
        fees = fees.reindex(index=close.index, columns=close.columns).fillna(0.)
    net = market - fees
    initial = float(account.daily.equity_previous.iloc[0])
    residual = net.sum(axis=1) - (account.daily.equity_after_trade - account.daily.equity_previous)
    if not np.allclose(residual, 0., atol=1e-8 * initial, rtol=0):
        raise ArithmeticError("Per-stock P&L does not reconcile to account")
    total = pd.DataFrame({"gross_pnl": market.sum(), "fees": fees.sum(), "net_pnl": net.sum(),
                          "contribution_to_total_return": net.sum() / initial})
    total.index = total.index.copy()
    total.index.name = "ticker"
    if not np.isclose(total.net_pnl.sum(), account.daily.equity_after_trade.iloc[-1] - initial,
                      atol=1e-8 * initial, rtol=0):
        raise ArithmeticError("Total P&L does not reconcile")
    daily = pd.concat({"gross_pnl": market.stack(), "fees": fees.stack(), "net_pnl": net.stack(),
                       "daily_return_contribution": net.div(account.daily.equity_previous, axis=0).stack()}, axis=1)
    daily.index.names = ["date", "ticker"]
    return total, daily, float(residual.abs().max())


def ic_records(score, close, horizon=20):
    if not isinstance(horizon, int) or horizon < 1:
        raise ValueError("horizon must be a positive integer")
    rows = []
    for x in monthly_schedule(close.index).itertuples(index=False):
        j = close.index.get_loc(x.execution_date)
        if j + horizon >= len(close):
            continue
        xy = pd.DataFrame({"score": score.loc[x.signal_date],
                           "future": close.iloc[j+horizon] / close.iloc[j] - 1}).dropna()
        rho = np.nan
        if len(xy) >= 10 and xy.score.nunique() > 1 and xy.future.nunique() > 1:
            rho = xy.score.rank().corr(xy.future.rank())
        rows.append([x.signal_date, x.execution_date, close.index[j+horizon], rho, len(xy)])
    return pd.DataFrame(rows, columns=["signal_date", "execution_date", "outcome_date", "rank_ic", "n_assets"])


def perf(r, b):
    if not r.index.equals(b.index) or not np.isfinite(r).all() or (r <= -1).any():
        raise ValueError("Invalid or unaligned return series")
    nav = np.r_[1., (1+r).cumprod().to_numpy()]
    vol = r.std(ddof=1) * np.sqrt(252)
    active = r-b
    te = active.std(ddof=1) * np.sqrt(252)
    return {"n_days": len(r), "total_return": nav[-1]-1,
            "cagr": nav[-1]**(252/len(r))-1, "ann_vol": vol,
            "sharpe_rf_zero": 252*r.mean()/vol if vol > 1e-14 else np.nan,
            "max_drawdown": (nav/np.maximum.accumulate(nav)-1).min(),
            "ir_vs_universe": 252*active.mean()/te if te > 1e-14 else np.nan}


def concentration(decisions):
    sets = [set(x.split("|")) for x in decisions.query("status == 'target_scheduled'").selected]
    if not sets:
        return pd.DataFrame(columns=["ticker", "selected_months", "fraction"])
    names = sorted(set.union(*sets))
    return pd.DataFrame([{"ticker": x, "selected_months": sum(x in s for s in sets),
                          "fraction": sum(x in s for s in sets)/len(sets)} for x in names])


def split_audit(data):
    rows = []
    if data.splits is not None:
        for col in data.splits:
            for date in data.splits.index[data.splits[col].gt(0) & data.splits[col].ne(1)]:
                j = data.splits.index.get_loc(date)
                before = data.volume[col].iloc[max(0,j-5):j].median()
                after = data.volume[col].iloc[j:j+5].median()
                rows.append([date, col, data.splits.loc[date,col], before, after,
                             after/before if before > 0 else np.nan])
    return pd.DataFrame(rows, columns=["date", "ticker", "split_ratio", "volume_median_before5",
                                       "volume_median_after5", "after_before_ratio"])


def run_audit(data: Data, cost_bps=10., n=10, initial=1e6, leave_one_out=True):
    validate(data)
    if not 1 <= n <= len(data.close.columns):
        raise ValueError("n must be within the stock universe")
    c, v = data.close, data.volume
    score = volume_score(v)
    dynamic = score_account(c, score, n, cost_bps, initial)
    static, frozen = static_controls(c, dynamic, cost_bps, initial)
    # Same initial execution date as volume strategy, not an earlier benchmark entry.
    base_targets = pd.DataFrame(np.nan, index=c.index, columns=c.columns)
    for date in dynamic.schedule.execution_date:
        if date >= pd.Timestamp(frozen["execution_date"]):
            base_targets.loc[date] = 1. / len(c.columns)
    benchmark = simulate_account(c, base_targets, initial, cost_bps)
    accounts = {"dynamic_volume": dynamic, **static, "universe_equal_weight": benchmark}
    definitions = [{"signal": "share_volume", "status": "RUN", "meaning": "log1p(mean20 provider share volume)"},
                   {"signal": "true_float_turnover", "status": "NOT_RUN", "meaning": "No verified historical float and publication timestamps; never use current float"}]
    if data.source_close is not None:
        raw = np.log1p((data.source_close * v).rolling(20, min_periods=20).mean())
        ds = preprocess_factors({"d": raw})["d"]
        accounts["dollar_activity_proxy"] = score_account(c, ds, n, cost_bps, initial)
        definitions.append({"signal": "dollar_activity_proxy", "status": "RUN",
                            "meaning": "mean20 provider Close*Volume; proxy, not audited traded dollars"})
    else:
        definitions.append({"signal": "dollar_activity_proxy", "status": "NOT_RUN",
                            "meaning": "source_close.csv absent; do not substitute dividend-adjusted close"})
    table = []
    for name, a in accounts.items():
        for label, mask in [("full", np.ones(len(c), dtype=bool)),
                            *[(str(y), c.index.year == y) for y in sorted(set(c.index.year))]]:
            r, b = a.daily.net_return.loc[mask], benchmark.daily.net_return.loc[mask]
            table.append({"strategy": name, "period": label, **perf(r,b),
                          "fees": a.daily.fees.loc[mask].sum()})
    summary, detail, residual = attribution(c, dynamic)
    exclusion = []
    ic = ic_records(score, c)
    if leave_one_out and len(c.columns) <= n:
        raise ValueError("Leave-one-out requires at least n+1 stocks; use --no-leave-one-out")
    for ticker in c.columns if leave_one_out else []:
        cc, vv = c.drop(columns=ticker), v.drop(columns=ticker)
        ss = volume_score(vv)  # Re-estimate cross-section, not subtract old contribution.
        a = score_account(cc, ss, n, cost_bps, initial)
        bt = base_targets.drop(columns=ticker).copy()
        bt.loc[bt.notna().any(axis=1)] = 1./len(cc.columns)
        b = simulate_account(cc, bt, initial, cost_bps)
        m = perf(a.daily.net_return, b.daily.net_return)
        exclusion.append({"excluded": ticker, **m,
                          "cagr_change_vs_original": m["cagr"]-table[0]["cagr"],
                          "mean_rank_ic": ic_records(ss,cc).rank_ic.mean()})
    # Unit dependence: multiply one asset's whole volume series by 2, not a split correction.
    original = dynamic.decisions.query("status == 'target_scheduled'").set_index("signal_date")
    stress = []
    for ticker in c.columns:
        vv = v.copy(); vv[ticker] *= 2.
        _, logs, _ = make_targets(c, volume_score(vv), n_stocks=n)
        new = logs["portfolio"].query("status == 'target_scheduled'").set_index("signal_date")
        changed = sum(set(original.loc[d,"selected"].split("|")) != set(new.loc[d,"selected"].split("|"))
                      for d in original.index.intersection(new.index))
        stress.append({"ticker_scaled": ticker, "multiplier": 2., "changed_selections": changed,
                       "n_compared": len(original.index.intersection(new.index))})
    return {"accounts": accounts, "comparison": pd.DataFrame(table), "frozen": frozen,
            "attribution": summary, "attribution_daily": detail, "attribution_residual": residual,
            "leave_one_out": pd.DataFrame(exclusion), "rank_ic": ic,
            "concentration": concentration(dynamic.decisions), "definitions": pd.DataFrame(definitions),
            "unit_stress": pd.DataFrame(stress), "split_audit": split_audit(data)}


def compare_previous(folder, account):
    """New download is NOT presumed identical to the old V2.3 run."""
    path = folder / "daily_log_volume_20d.csv"
    old = pd.read_csv(path, index_col=0, parse_dates=True)
    new = account.daily
    common = old.index.intersection(new.index)
    if not len(common):
        raise ValueError("Reference V2.3 has no overlapping dates")
    return {"source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "dates_equal": old.index.equals(new.index), "n_common": len(common),
            "max_abs_net_return_difference": float((old.loc[common,"net_return"]-new.loc[common,"net_return"]).abs().max()),
            "warning": "Same outputs do not prove point-in-time data validity"}


def save_run(out, data, result, metadata):
    out.mkdir(parents=True, exist_ok=False)
    snap = out / "snapshot"; snap.mkdir()
    for name in ("close", "volume", "source_close", "splits"):
        f = getattr(data,name)
        if f is not None:
            f.to_csv(snap / f"{name}.csv", index_label="date")
    for name in ("comparison", "leave_one_out", "rank_ic", "concentration", "definitions", "unit_stress", "split_audit"):
        result[name].to_csv(out / f"{name}.csv", index=False)
    result["attribution"].to_csv(out / "attribution.csv")
    result["attribution_daily"].to_csv(out / "attribution_daily.csv")
    for name, a in result["accounts"].items():
        save_account(a, out / "accounts" / name)
    (out / "frozen_selection.json").write_text(json.dumps(result["frozen"],indent=2),encoding="utf8")
    manifest = {"version": "V2.4", "base_commit": BASE_COMMIT,
                "created_utc": datetime.now(timezone.utc).isoformat(), **metadata,
                "attribution_max_abs_residual": result["attribution_residual"],
                "python": platform.python_version(),
                "versions": {p: md.version(p) for p in ("numpy","pandas","exchange-calendars")},
                "files_sha256": {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in sorted(out.rglob("*")) if p.is_file()}}
    (out / "RUN_INFO.json").write_text(json.dumps(manifest,indent=2),encoding="utf8")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    m = p.add_mutually_exclusive_group(required=True)
    m.add_argument("--demo", action="store_true"); m.add_argument("--csv-dir", type=Path)
    m.add_argument("--download", action="store_true")
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--start", default="2018-01-01"); p.add_argument("--end", default="2025-01-01")
    p.add_argument("--cost-bps", type=float, default=10.); p.add_argument("--n-stocks", type=int, default=10)
    p.add_argument("--no-leave-one-out", action="store_true")
    p.add_argument("--reference-v23", type=Path)
    a = p.parse_args()
    if a.output.exists():
        p.error("Output path already exists. Choose a NEW path; no overwrite.")
    verify_engines()
    if a.demo:
        c,v = demo_data(); data = Data(c,v,c.copy(),v*0.)
        source = "SYNTHETIC DEMO -- NOT MARKET EVIDENCE"
    elif a.csv_dir:
        data = read_data(a.csv_dir); source = "CSV SNAPSHOT -- PROVENANCE REQUIRES REVIEW"
    else:
        data = download(a.start,a.end); source = "NEW YAHOO SNAPSHOT -- NOT AN EXACT V2.3 REPLAY"
    result = run_audit(data,a.cost_bps,a.n_stocks,leave_one_out=not a.no_leave_one_out)
    meta = {"source": source, "cost_bps": a.cost_bps, "n_stocks": a.n_stocks,
            "lookback": 20, "ic_horizon": 20, "leave_one_out": not a.no_leave_one_out,
            "first_date": str(data.close.index[0]), "last_date": str(data.close.index[-1]),
            "tickers": list(data.close.columns), "initial_cash": 1e6,
            "limits": ["retrospective selection of audit questions", "fixed survivorship-biased universe",
                       "provider adjustment basis not point-in-time certified", "idealized next-close fills",
                       "assumed proportional cost only", "no true float turnover", "no terminal liquidation"]}
    if a.download:
        meta.update(requested_start=a.start,requested_end_exclusive=a.end,yfinance_version=md.version("yfinance"))
    if a.reference_v23:
        meta["reference_v23"] = compare_previous(a.reference_v23,result["accounts"]["dynamic_volume"])
    save_run(a.output,data,result,meta)
    print(source)
    print("V2.4 RETROSPECTIVE AUDIT -- no untouched holdout or certified alpha")
    print(result["comparison"].query("period == 'full'").to_string(index=False))
    print("Max attribution reconciliation residual:",result["attribution_residual"])
    print("True float turnover: NOT RUN (historical data unavailable)")
    if "reference_v23" in meta:
        print("V2.3 reference comparison:",meta["reference_v23"])
    print("Saved:",a.output.resolve())


if __name__ == "__main__":
    main()
