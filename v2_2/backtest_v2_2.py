"""V2.2: long-only, self-financing holdings and proportional traded-value costs.

Reuse the unchanged V2.1 signals/calendar. Fractional units, next-close fills,
zero cash interest, no terminal liquidation. With adjusted input prices, units
are synthetic adjusted-price units, NOT literal brokerage shares. This is an
accounting research model, not a production execution simulator.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

# Read-only reuse of the sibling version; do not copy or modify V2.1.
V21_DIR = Path(__file__).resolve().parents[1] / "v2_1"
sys.path.insert(0, str(V21_DIR))
from backtest_v2_1 import (  # noqa: E402
    TICKERS, _eligible_at_signal, _validate_frame, combine_factors,
    compute_factors, demo_data, download_data, monthly_schedule, preprocess_factors,
)

BASE_COMMIT = "abd4242fe2a71d17a23fe3166b366853709e145e"
TRADE_COLUMNS = ["date", "ticker", "side", "input_price", "units_before", "unit_change",
                 "units_after", "signed_notional", "fee", "weight_before",
                 "target_weight", "weight_after"]


def solve_rebalance(values: np.ndarray, cash: float, target: np.ndarray,
                    cost_bps: float = 10.0) -> Rebalance:
    """Solve x + k*sum(abs(w*x - h)) = V for post-cost equity x.

    w is the desired fraction of POST-COST equity in each risky asset.
    sum(w) <= 1; its remainder is cash. k is charged on each actual buy/sell.
    The normalized scalar equation is strictly increasing for 0 <= k < 1.
    Bisection uses its feasible lower endpoint to avoid borrowing for fees.
    """
    h, w = np.asarray(values, dtype=float), np.asarray(target, dtype=float)
    if h.ndim != 1 or h.shape != w.shape or not h.size:
        raise ValueError("values and target must be equally sized nonempty vectors.")
    if not np.isfinite(h).all() or (h < 0).any() or not np.isfinite(cash) or cash < 0:
        raise ValueError("Long-only holdings and nonnegative finite cash are required.")
    if not np.isfinite(w).all() or (w < 0).any() or w.sum() > 1 + 1e-12:
        raise ValueError("Target must be finite, nonnegative, and sum to at most one.")
    if not np.isfinite(cost_bps) or not 0 <= cost_bps < 10000:
        raise ValueError("cost_bps must be finite and in [0, 10000).")
    if w.sum() > 1:  # Only repair floating-point summation, not economic leverage.
        w = w / w.sum()
    V = float(h.sum() + cash)
    if not np.isfinite(V) or V <= 0:
        raise ValueError("Pre-trade equity must be positive and finite.")
    k = cost_bps / 10000.0
    if np.max(np.abs(h - w * V)) <= 8 * np.finfo(float).eps * V:
        return Rebalance(h.copy(), np.zeros_like(h), np.zeros_like(h), float(cash))
    if k == 0:
        x = V
    else:
        p = h / V
        lo, hi = 0.0, 1.0
        for _ in range(80):
            mid = (lo + hi) / 2
            if mid + k * np.abs(w * mid - p).sum() <= 1:
                lo = mid
            else:
                hi = mid
        x = lo * V
    after = w * x
    trades = after - h
    fees = k * np.abs(trades)
    remaining = V - float(after.sum()) - float(fees.sum())
    if remaining < -1e-12 * V:
        raise ArithmeticError("Negative cash: self-financing solve failed.")
    # Ignore only machine-roundoff-sized residuals; never borrow to pay costs.
    remaining = max(remaining, 0.0)
    if abs(after.sum() + remaining + fees.sum() - V) > 1e-11 * V:
        raise ArithmeticError("Self-financing identity failed.")
    return Rebalance(after, trades, fees, remaining)


@dataclass
class Rebalance:
    values_after: np.ndarray
    trades: np.ndarray
    fees_by_asset: np.ndarray
    cash_after: float


@dataclass
class AccountResult:
    daily: pd.DataFrame
    units_after_close: pd.DataFrame
    weights_before_trade: pd.DataFrame
    weights_after_close: pd.DataFrame
    trades: pd.DataFrame
    targets: pd.DataFrame
    decisions: pd.DataFrame
    schedule: pd.DataFrame


def simulate_account(close: pd.DataFrame, targets: pd.DataFrame,
                     initial_cash: float = 1_000_000.0,
                     cost_bps: float = 10.0, calendar: str = "XNYS") -> AccountResult:
    """Execute supplied targets at their row's close. NaN row means NO order.

    Hold units fixed between trades; mark old holdings first, then trade and
    deduct fees. A zero target row liquidates; a missing row retains holdings.
    Caller must construct targets causally. backtest() does this via V2.1 timing.
    """
    _validate_frame(close, "close")
    _validate_frame(targets, "targets")
    if not close.index.equals(targets.index) or not close.columns.equals(targets.columns):
        raise ValueError("close and targets must have identical axes.")
    monthly_schedule(close.index, calendar)  # Reject missing exchange sessions.
    if not np.isfinite(initial_cash) or initial_cash <= 0:
        raise ValueError("initial_cash must be positive and finite.")
    if not np.isfinite(cost_bps) or not 0 <= cost_bps < 10000:
        raise ValueError("cost_bps must be finite and in [0, 10000).")
    orders = targets.notna().any(axis=1)
    t = targets.loc[orders]
    if (t.isna().any().any() or not np.isfinite(t).all().all()
            or (t < 0).any().any() or (t.sum(axis=1) > 1 + 1e-12).any()):
        raise ValueError("An order must give all weights, nonnegative, summing to <= 1.")
    prices, target_values = close.to_numpy(float), targets.to_numpy(float)
    units = np.zeros(close.shape[1])
    cash = previous = float(initial_cash)
    days, transactions, unit_rows, before_rows, after_rows = [], [], [], [], []
    for j, date in enumerate(close.index):
        px = prices[j]
        order = bool(orders.iloc[j])
        required = (units > 0) | ((target_values[j] > 0) if order else False)
        if ((~np.isfinite(px) | (px <= 0)) & required).any():
            raise ValueError(f"{date.date()}: missing/invalid selected or held price; no filling/reselection.")
        h = np.zeros_like(units)
        np.multiply(units, px, out=h, where=units > 0)
        cash_before = cash
        before = float(h.sum() + cash)
        if not np.isfinite(before) or before <= 0:
            raise ArithmeticError("Nonpositive or nonfinite equity.")
        w_before = h / before
        fees = buys = sells = 0.0
        if order:
            plan = solve_rebalance(h, cash, target_values[j], cost_bps)
            fees = float(plan.fees_by_asset.sum())
            buys = float(np.maximum(plan.trades, 0).sum())
            sells = float(np.maximum(-plan.trades, 0).sum())
            new_units = units.copy()
            changed = plan.trades != 0
            np.divide(plan.values_after, px, out=new_units, where=changed)
            # Exited assets have a valid price (they were held before this trade).
            cash = plan.cash_after
            after = float(plan.values_after.sum() + cash)
            for i in np.flatnonzero(changed):
                transactions.append([
                    date, close.columns[i], "BUY" if plan.trades[i] > 0 else "SELL",
                    px[i], units[i], new_units[i] - units[i], new_units[i],
                    plan.trades[i], plan.fees_by_asset[i], w_before[i], target_values[j, i],
                    plan.values_after[i] / after,
                ])
            units = new_units
            h = plan.values_after
        after = float(h.sum() + cash)
        identity_error = before - after - fees
        if abs(identity_error) > 1e-10 * before:
            raise ArithmeticError("Daily accounting identity failed.")
        days.append({
            "equity_previous": previous, "equity_before_trade": before,
            "equity_after_trade": after, "cash_before": cash_before, "cash_after": cash,
            "market_pnl": before - previous, "fees": fees,
            "buy_notional": buys, "sell_notional": sells,
            "traded_fraction": (buys + sells) / before,
            "half_traded_fraction": (buys + sells) / (2 * before),
            "gross_return_on_net_holdings": before / previous - 1,
            "net_return": after / previous - 1,
            "self_financing_residual": identity_error, "target_requested": order,
        })
        unit_rows.append(units.copy())
        before_rows.append(w_before)
        after_rows.append(h / after)
        previous = after
    frame = lambda rows: pd.DataFrame(rows, index=close.index, columns=close.columns)
    return AccountResult(pd.DataFrame(days, index=close.index), frame(unit_rows),
                         frame(before_rows), frame(after_rows),
                         pd.DataFrame(transactions, columns=TRADE_COLUMNS), targets.copy(),
                         pd.DataFrame(), pd.DataFrame())


def make_targets(close: pd.DataFrame, scores: pd.DataFrame, n_stocks: int = 10,
                 n_groups: int | None = None, calendar: str = "XNYS"):
    """V2.1 signal selection, but return orders rather than proxy returns."""
    _validate_frame(close, "close")
    _validate_frame(scores, "scores")
    if not close.index.equals(scores.index) or not close.columns.equals(scores.columns):
        raise ValueError("close and scores must have identical axes.")
    if not isinstance(n_stocks, int) or n_stocks < 1:
        raise ValueError("n_stocks must be a positive integer.")
    if n_groups is not None and (not isinstance(n_groups, int) or n_groups < 2):
        raise ValueError("n_groups must be an integer >= 2.")
    schedule = monthly_schedule(close.index, calendar)
    labels = ["portfolio"] if n_groups is None else [f"Q{i+1}" for i in range(n_groups)]
    targets = {g: pd.DataFrame(np.nan, index=close.index, columns=close.columns) for g in labels}
    logs = {g: [] for g in labels}
    for row in schedule.itertuples(index=False):
        f = _eligible_at_signal(close, scores, row.signal_date)
        rec = row._asdict() | {"n_eligible": len(f)}
        selected, reason = {}, "skipped_insufficient_factors"
        if n_groups is None and len(f) >= n_stocks:
            selected["portfolio"] = f.sort_values(ascending=False, kind="mergesort").iloc[:n_stocks].index
        elif n_groups is not None and len(f) >= n_groups * 2:
            try:
                groups = pd.qcut(f, n_groups, labels=labels)
                selected = {g: groups.index[groups == g] for g in labels}
            except ValueError:
                reason = "skipped_duplicate_quantile_edges"
        for g in labels:
            if g not in selected:
                logs[g].append(rec | {"status": reason, "selected": ""})
                continue
            names = selected[g]
            targets[g].loc[row.execution_date] = 0.0
            targets[g].loc[row.execution_date, names] = 1.0 / len(names)
            logs[g].append(rec | {"status": "target_scheduled", "selected": "|".join(map(str, names))})
    cols = ["signal_date", "execution_date", "first_return_date", "n_eligible", "status", "selected"]
    return targets, {g: pd.DataFrame(logs[g], columns=cols) for g in labels}, schedule


def backtest(close: pd.DataFrame, scores: pd.DataFrame, n_stocks: int = 10,
             cost_bps: float = 10.0, initial_cash: float = 1_000_000.0,
             calendar: str = "XNYS") -> AccountResult:
    targets, logs, schedule = make_targets(close, scores, n_stocks, calendar=calendar)
    r = simulate_account(close, targets["portfolio"], initial_cash, cost_bps, calendar)
    r.decisions, r.schedule = logs["portfolio"], schedule
    return r


def layered_backtest(close: pd.DataFrame, scores: pd.DataFrame, n_groups: int = 5,
                     cost_bps: float = 10.0, initial_cash: float = 1_000_000.0):
    targets, logs, schedule = make_targets(close, scores, n_groups=n_groups)
    result = {}
    for g, target in targets.items():
        r = simulate_account(close, target, initial_cash, cost_bps)
        r.decisions, r.schedule = logs[g], schedule
        result[g] = r
    return result


def save_account(r: AccountResult, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name in ["daily", "units_after_close", "weights_before_trade", "weights_after_close", "targets"]:
        getattr(r, name).to_csv(out / f"{name}.csv", index_label="date")
    for name in ["trades", "decisions", "schedule"]:
        getattr(r, name).to_csv(out / f"{name}.csv", index=False)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    modes = p.add_mutually_exclusive_group(required=True)
    modes.add_argument("--demo", action="store_true")
    modes.add_argument("--csv-dir", type=Path, help="V2.1 outputs_demo or another folder with close.csv/volume.csv")
    modes.add_argument("--download", action="store_true", help="Optional Yahoo path; not validated here")
    p.add_argument("--start", default="2018-01-01")
    p.add_argument("--end", default="2024-12-31", help="Exclusive, as in V2.1")
    p.add_argument("--n-stocks", type=int, default=10)
    p.add_argument("--cost-bps", type=float, default=10)
    p.add_argument("--initial-cash", type=float, default=1_000_000)
    p.add_argument("--output", type=Path, default=Path("outputs_v2_2_demo"))
    args = p.parse_args()
    if args.output.exists():
        p.error("Output path already exists; choose a NEW path. No files were overwritten.")
    if args.demo:
        close, volume = demo_data()
        source = "SYNTHETIC DEMO - NOT REAL MARKET DATA"
    elif args.download:
        close, volume = download_data(TICKERS, args.start, args.end)
        source = "Yahoo adjusted historical data; fixed survivorship-biased universe"
    else:
        close = pd.read_csv(args.csv_dir / "close.csv", index_col=0, parse_dates=True)
        volume = pd.read_csv(args.csv_dir / "volume.csv", index_col=0, parse_dates=True)
        source = "User CSV - provenance and adjustment convention must be checked separately"
    scores = combine_factors(preprocess_factors(compute_factors(close, volume)))
    net = backtest(close, scores, args.n_stocks, args.cost_bps, args.initial_cash)
    gross = backtest(close, scores, args.n_stocks, 0, args.initial_cash)
    layers = layered_backtest(close, scores, cost_bps=args.cost_bps, initial_cash=args.initial_cash)
    args.output.mkdir(parents=True, exist_ok=False)
    save_account(net, args.output)
    save_account(gross, args.output / "zero_cost_reference")
    for g, result in layers.items():
        save_account(result, args.output / "quintiles" / g)
    for name, data in [("close", close), ("volume", volume), ("composite_factor", scores)]:
        data.to_csv(args.output / f"{name}.csv", index_label="date")
    pd.DataFrame({"net_equity": net.daily.equity_after_trade,
                  "zero_cost_equity": gross.daily.equity_after_trade,
                  "net_return": net.daily.net_return,
                  "zero_cost_return": gross.daily.net_return}).to_csv(args.output / "comparison.csv", index_label="date")
    files = sorted(args.output.rglob("*.csv"))
    metadata = {
        "version": "V2.2", "base_commit": BASE_COMMIT, "data_mode": source,
        "initial_cash": args.initial_cash, "cost_bps_per_buy_or_sell_notional": args.cost_bps,
        "n_stocks": args.n_stocks, "calendar": "XNYS", "lookback": 20,
        "first_date": str(close.index[0].date()), "last_date": str(close.index[-1].date()),
        "signal": "month-end close", "execution": "next session close",
        "fees": "deducted on execution day from portfolio cash; buys and sells separately",
        "target_weights": "fractions of equity AFTER paying fees",
        "units": "fractional; synthetic adjusted-price units if input prices are adjusted",
        "cash_interest": 0, "terminal_liquidation": False,
        "limitations": ["idealized closing fills", "no lots, liquidity, impact, or settlement model",
                        "no separate corporate-action cash flows", "fixed biased universe",
                        "constant assumed bps is not calibrated real-world total cost",
                        "no out-of-sample performance or Sharpe/IR certification"],
        "versions": {x: importlib.metadata.version(x) for x in ["numpy", "pandas", "exchange-calendars"]},
        "input_sha256": {x: hashlib.sha256((args.output / x).read_bytes()).hexdigest()
                         for x in ["close.csv", "volume.csv"]},
        "output_sha256": {str(f.relative_to(args.output)): hashlib.sha256(f.read_bytes()).hexdigest() for f in files},
    }
    if args.download:
        metadata.update(requested_start_inclusive=args.start, requested_end_exclusive=args.end)
        metadata["versions"]["yfinance"] = importlib.metadata.version("yfinance")
    (args.output / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(source)
    print("V2.2 ACCOUNTING MODEL: fixed units between trades; net of ASSUMED proportional costs.")
    print("No real-market performance certification. No terminal liquidation.")
    print(net.decisions.to_string(index=False))
    print(f"Initial equity: {args.initial_cash:.6f}")
    print(f"Ending equity (assumed costs): {net.daily.equity_after_trade.iloc[-1]:.6f}")
    print(f"Ending equity (zero-cost reference): {gross.daily.equity_after_trade.iloc[-1]:.6f}")
    print(f"Total paid fees: {net.daily.fees.sum():.6f}")
    print(f"Max self-financing residual: {net.daily.self_financing_residual.abs().max():.3e}")
    print(f"Saved diagnostics to {args.output.resolve()}")


if __name__ == "__main__":
    main()
