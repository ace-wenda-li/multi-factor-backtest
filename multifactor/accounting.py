"""Long-only, self-financing holdings with proportional traded-notional fees.

Fractional units, next-close fills, zero cash interest and no terminal
liquidation are assumed. Adjusted input prices imply synthetic adjusted-price
units, rather than literal brokerage shares.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .signals import (
    TICKERS, _eligible_at_signal, _validate_frame, combine_factors,
    compute_factors, demo_data, download_data, monthly_schedule, preprocess_factors,
)

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
    Caller must construct targets causally. backtest() uses the month-end signal schedule.
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
    """Create next-close target orders from the month-end signal schedule."""
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
