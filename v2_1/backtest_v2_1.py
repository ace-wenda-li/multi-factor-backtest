"""V2.1: causal cross-sectional factors and explicit next-close execution.

Based on ace-wenda-li/multi-factor-backtest at 9f8b17e8e451aca45afe98a3a1cdd9729056e9d2.
This is a standalone timing-validation revision, not a production backtester.
Returns are GROSS daily equal-weight proxies. Weight drift, real turnover,
transaction costs and performance-statistic corrections belong to V2.2/V2.3.

Offline demo: python backtest_v2_1.py --demo
Tests:        python -m pytest -q tests
Real data:    python backtest_v2_1.py --download --output outputs_v2_1_real
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import exchange_calendars as xcals
import numpy as np
import pandas as pd

BASE_COMMIT = "9f8b17e8e451aca45afe98a3a1cdd9729056e9d2"
TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA", "JPM", "V", "UNH",
    "HD", "PG", "MA", "DIS", "BAC", "XOM", "PFE", "CSCO", "VZ", "ADBE",
    "NFLX", "INTC", "T", "MRK", "PEP", "KO", "WMT", "CVX", "ABT", "TMO",
]


def _validate_frame(df: pd.DataFrame, name: str) -> None:
    if not isinstance(df, pd.DataFrame) or df.empty:
        raise ValueError(f"{name} must be a nonempty DataFrame.")
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError(f"{name} must have a DatetimeIndex.")
    if df.index.tz is not None or not df.index.equals(df.index.normalize()):
        raise ValueError(f"{name}: use timezone-naive, normalized exchange session dates.")
    if df.index.has_duplicates or not df.index.is_monotonic_increasing:
        raise ValueError(f"{name}: dates must be unique and sorted.")
    if df.columns.has_duplicates:
        raise ValueError(f"{name}: duplicate ticker columns.")
    if not all(pd.api.types.is_numeric_dtype(t) for t in df.dtypes):
        raise ValueError(f"{name}: all columns must be numeric.")


def compute_factors(close: pd.DataFrame, volume: pd.DataFrame,
                    lookback: int = 20) -> dict[str, pd.DataFrame]:
    """Keep the original four formulas; no implicit price/volume imputation."""
    _validate_frame(close, "close")
    _validate_frame(volume, "volume")
    if not close.index.equals(volume.index) or not close.columns.equals(volume.columns):
        raise ValueError("close and volume must have identical dates and ticker order.")
    if lookback < 2:
        raise ValueError("lookback must be at least 2.")
    if (close <= 0).any().any() or (volume < 0).any().any():
        raise ValueError("Non-missing close must be positive; volume must be nonnegative.")
    returns = close.pct_change(fill_method=None)
    return {
        "momentum": close.pct_change(lookback, fill_method=None),
        "volatility": -returns.rolling(lookback, min_periods=lookback).std() * np.sqrt(252),
        # Legacy key retained. This is log trading volume, NOT share turnover.
        "turnover": np.log1p(volume.rolling(lookback, min_periods=lookback).mean()),
        "reversal": -close.pct_change(5, fill_method=None),
    }


def winsorize(df: pd.DataFrame, limits: tuple[float, float] = (-3, 3)) -> pd.DataFrame:
    """Clip across stocks on EACH date, not across the full time history."""
    if len(limits) != 2 or not limits[0] <= 0 <= limits[1]:
        raise ValueError("limits must straddle zero, e.g. (-3, 3).")
    clean = df.replace([np.inf, -np.inf], np.nan)
    row_mean = clean.mean(axis=1)
    row_std = clean.std(axis=1, ddof=1)
    # axis=0 aligns date-indexed thresholds with rows (not a time aggregation).
    return clean.clip(lower=row_mean + limits[0] * row_std,
                      upper=row_mean + limits[1] * row_std, axis=0)


def preprocess_factors(factor_dict: Mapping[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    if not factor_dict:
        raise ValueError("At least one factor is required.")
    processed = {}
    reference = next(iter(factor_dict.values()))
    for name, df in factor_dict.items():
        _validate_frame(df, name)
        if not df.index.equals(reference.index) or not df.columns.equals(reference.columns):
            raise ValueError("All factors must have the same dates and ticker order.")
        clipped = winsorize(df)
        row_mean = clipped.mean(axis=1)
        row_std = clipped.std(axis=1, ddof=1)
        z = clipped.sub(row_mean, axis=0).div(row_std.where(row_std > 0), axis=0)
        # A constant but observable cross section carries zero ranking information.
        # Missing entries remain NaN; a row with only one observation remains NaN.
        constant = row_std.eq(0) & clipped.count(axis=1).ge(2)
        if constant.any():
            z.loc[constant] = clipped.loc[constant].where(clipped.loc[constant].isna(), 0.0)
        processed[name] = z
    return processed


def combine_factors(processed_factors: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    if not processed_factors:
        raise ValueError("At least one factor is required.")
    frames = list(processed_factors.values())
    reference = frames[0]
    for df in frames:
        if not df.index.equals(reference.index) or not df.columns.equals(reference.columns):
            raise ValueError("All factors must have identical axes.")
    result = frames[0].copy()
    for frame in frames[1:]:
        result = result + frame  # NaN propagates: all four factors must be observable.
    return result / len(frames)


def monthly_schedule(index: pd.DatetimeIndex, calendar: str = "XNYS") -> pd.DataFrame:
    """Month's last exchange session -> next session close -> first return date.

    Validate a complete trading-date index against an exchange calendar, so a
    missing row is not silently mistaken for a holiday. A partial final month
    does not generate an artificial month-end signal. Calendar dates are
    exogenous; no future price/volume is consulted to construct this schedule.
    """
    _validate_frame(pd.DataFrame({"dummy": np.zeros(len(index))}, index=index), "index")
    calendar_start = index[0].to_period("M").start_time
    calendar_end = index[-1].to_period("M").end_time.normalize() + pd.Timedelta(days=15)
    cal = xcals.get_calendar(calendar, start=calendar_start, end=calendar_end)
    # Calendar bounds may be holidays; select actual session labels directly.
    sessions = cal.sessions[(cal.sessions >= calendar_start) & (cal.sessions <= calendar_end)]
    expected = sessions[(sessions >= index[0]) & (sessions <= index[-1])]
    missing, extra = expected.difference(index), index.difference(expected)
    if len(missing) or len(extra):
        raise ValueError(f"Incomplete {calendar} date index. Missing sessions: "
                         f"{missing.strftime('%Y-%m-%d').tolist()}; non-sessions: "
                         f"{extra.strftime('%Y-%m-%d').tolist()}.")
    month_ends = pd.Series(sessions, index=sessions).groupby(sessions.to_period("M")).last()
    rows = []
    for signal in month_ends:
        if signal not in index:
            continue
        p = sessions.get_loc(signal)
        execution, first_return = sessions[p + 1], sessions[p + 2]
        if execution > index[-1]:
            continue  # No execution within the available sample.
        rows.append({"signal_date": signal, "execution_date": execution,
                     "first_return_date": first_return})
    return pd.DataFrame(rows, columns=["signal_date", "execution_date", "first_return_date"])


@dataclass
class BacktestResult:
    gross_returns: pd.Series
    weights_after_close: pd.DataFrame
    weights_for_return: pd.DataFrame
    decision_log: pd.DataFrame
    schedule: pd.DataFrame


def _eligible_at_signal(close: pd.DataFrame, scores: pd.DataFrame,
                        signal: pd.Timestamp) -> pd.Series:
    # Only information at the signal close is used to choose names.
    f = scores.loc[signal].replace([np.inf, -np.inf], np.nan)
    observable = close.loc[signal].gt(0) & np.isfinite(close.loc[signal])
    return f.where(observable).dropna().sort_index()


def _simulate(close: pd.DataFrame, targets: pd.DataFrame,
              decision_log: list[dict], schedule: pd.DataFrame) -> BacktestResult:
    # Rows without an order retain the previous target; cash before first order.
    after_close = targets.ffill().fillna(0.0)
    # CRITICAL: a close-t order cannot earn close-(t-1) -> close-t returns.
    for_return = after_close.shift(1, fill_value=0.0)
    stock_returns = close.pct_change(fill_method=None)
    trading_today = targets.notna().all(axis=1)
    required_prices = (for_return > 0) | (trading_today.to_numpy()[:, None] & (targets > 0))
    bad_prices = required_prices & (~np.isfinite(close) | (close <= 0))
    bad_returns = (for_return > 0) & ~np.isfinite(stock_returns)
    if bad_prices.any().any() or bad_returns.any().any():
        raise ValueError("A selected/held asset has a missing or invalid price. "
                         "Do not forward-fill, drop the day, or reselect using future availability.")
    gross = (for_return * stock_returns.fillna(0.0)).sum(axis=1)
    gross.name = "gross_equal_weight_proxy"
    return BacktestResult(gross, after_close, for_return,
                          pd.DataFrame(decision_log, columns=[
                              "signal_date", "execution_date", "first_return_date",
                              "n_eligible", "status", "selected",
                          ]), schedule)


def backtest(close: pd.DataFrame, composite_factor: pd.DataFrame, n_stocks: int = 10,
             rebalance_freq: str = "ME", cost_bps: float = 0,
             calendar: str = "XNYS") -> BacktestResult:
    """Monthly name selection, next-close execution, gross fixed-weight proxy.

    V2.1 deliberately disables the old cost calculation rather than label it
    reliable net performance. Constant daily target weights imply frictionless
    daily weight resets; drift and traded-notional accounting are NOT fixed yet.
    """
    if n_stocks < 1:
        raise ValueError("n_stocks must be positive.")
    if rebalance_freq != "ME":
        raise ValueError("V2.1 implements month-end signals only.")
    if not np.isfinite(cost_bps) or cost_bps != 0:
        raise ValueError("V2.1 is GROSS timing validation only; costs are deferred to V2.2.")
    _validate_frame(close, "close")
    _validate_frame(composite_factor, "composite_factor")
    if not close.index.equals(composite_factor.index) or not close.columns.equals(composite_factor.columns):
        raise ValueError("close and composite_factor must have identical axes.")
    schedule = monthly_schedule(close.index, calendar)
    targets = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    log = []
    for row in schedule.itertuples(index=False):
        f = _eligible_at_signal(close, composite_factor, row.signal_date)
        record = row._asdict() | {"n_eligible": len(f)}
        if len(f) < n_stocks:
            log.append(record | {"status": "skipped_insufficient_factors", "selected": ""})
            continue  # Keep existing holdings, not a silent gap in returns.
        selected = f.sort_values(ascending=False, kind="mergesort").iloc[:n_stocks].index
        targets.loc[row.execution_date] = 0.0
        targets.loc[row.execution_date, selected] = 1.0 / n_stocks
        log.append(record | {"status": "executed", "selected": "|".join(map(str, selected))})
    return _simulate(close, targets, log, schedule)


def layered_backtest(close: pd.DataFrame, composite_factor: pd.DataFrame,
                     n_groups: int = 5, calendar: str = "XNYS") -> dict[str, BacktestResult]:
    """Original qcut grouping, with the SAME calendar and execution convention."""
    _validate_frame(close, "close")
    _validate_frame(composite_factor, "composite_factor")
    if n_groups < 2:
        raise ValueError("n_groups must be at least two.")
    if not close.index.equals(composite_factor.index) or not close.columns.equals(composite_factor.columns):
        raise ValueError("close and composite_factor must have identical axes.")
    schedule = monthly_schedule(close.index, calendar)
    labels = [f"Q{i+1}" for i in range(n_groups)]
    targets = {g: pd.DataFrame(np.nan, index=close.index, columns=close.columns) for g in labels}
    logs: dict[str, list[dict]] = {g: [] for g in labels}
    for row in schedule.itertuples(index=False):
        f = _eligible_at_signal(close, composite_factor, row.signal_date)
        record = row._asdict() | {"n_eligible": len(f)}
        reason = "skipped_insufficient_factors"
        groups = None
        if len(f) >= n_groups * 2:
            try:
                groups = pd.qcut(f, n_groups, labels=labels)
            except ValueError:
                reason = "skipped_duplicate_quantile_edges"
        for g in labels:
            if groups is None:
                logs[g].append(record | {"status": reason, "selected": ""})
                continue
            selected = groups.index[groups == g]
            targets[g].loc[row.execution_date] = 0.0
            targets[g].loc[row.execution_date, selected] = 1.0 / len(selected)
            logs[g].append(record | {"status": "executed", "selected": "|".join(map(str, selected))})
    return {g: _simulate(close, targets[g], logs[g], schedule) for g in labels}


def demo_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Artificial data ONLY. Not a market return or an investment result."""
    cal = xcals.get_calendar("XNYS", start="2024-01-01", end="2024-06-15")
    index = cal.sessions_in_range("2024-01-02", "2024-05-15")
    rng = np.random.default_rng(21)
    names = [f"S{i:02d}" for i in range(12)]
    close = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.01, (len(index), len(names))), axis=0)),
                         index=index, columns=names)
    volume = pd.DataFrame(rng.integers(10000, 1000000, close.shape).astype(float),
                          index=index, columns=names)
    return close, volume


def download_data(tickers: list[str], start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """end is exclusive, matching yfinance. No price or volume forward-fill."""
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("For real data, first install yfinance in this environment.") from exc
    data = yf.download(tickers, start=start, end=end, auto_adjust=True,
                       progress=False, group_by="column", multi_level_index=True,
                       keepna=True, threads=False)
    if data is None or data.empty:
        raise ValueError("No Yahoo data returned; no performance result was produced.")
    close, volume = data["Close"].copy(), data["Volume"].copy()
    missing = set(tickers) - set(close.columns)
    if missing:
        raise ValueError(f"Download missing tickers: {sorted(missing)}")
    close, volume = close.reindex(columns=tickers), volume.reindex(columns=tickers)
    for frame in (close, volume):
        frame.index = pd.DatetimeIndex(frame.index).tz_localize(None).normalize()
    if close.isna().all().any() or volume.isna().all().any():
        raise ValueError("At least one ticker has no usable data. Do not silently remove it.")
    return close.sort_index(), volume.sort_index()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--demo", action="store_true")
    mode.add_argument("--download", action="store_true")
    mode.add_argument("--csv-dir", type=Path, help="Contains close.csv and volume.csv; first column is date.")
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--end", default="2024-12-31", help="Exclusive; preserves original requested interval.")
    parser.add_argument("--n-stocks", type=int, default=10)
    parser.add_argument("--output", type=Path, default=Path("outputs_v2_1"))
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("Output directory must be new or empty; choose a new --output path.")
    if args.demo:
        close, volume = demo_data()
        mode_label = "SYNTHETIC DEMO - NOT REAL MARKET DATA"
    elif args.download:
        close, volume = download_data(TICKERS, args.start, args.end)
        mode_label = "Yahoo adjusted historical data; fixed survivorship-biased universe"
    else:
        close = pd.read_csv(args.csv_dir / "close.csv", index_col=0, parse_dates=True)
        volume = pd.read_csv(args.csv_dir / "volume.csv", index_col=0, parse_dates=True)
        mode_label = "User-provided CSV data; provenance must be checked separately"
    composite = combine_factors(preprocess_factors(compute_factors(close, volume)))
    result = backtest(close, composite, n_stocks=args.n_stocks)
    groups = layered_backtest(close, composite)
    args.output.mkdir(parents=True, exist_ok=True)
    outputs = {
        "close.csv": close, "volume.csv": volume, "composite_factor.csv": composite,
        "gross_returns.csv": result.gross_returns,
        "weights_after_close.csv": result.weights_after_close,
        "weights_for_return.csv": result.weights_for_return,
        "quintile_gross_returns.csv": pd.DataFrame({g: r.gross_returns for g, r in groups.items()}),
    }
    for filename, frame in outputs.items():
        frame.to_csv(args.output / filename, index_label="date")
    result.schedule.to_csv(args.output / "schedule.csv", index=False)
    result.decision_log.to_csv(args.output / "decision_log.csv", index=False)
    for g, r in groups.items():
        r.decision_log.to_csv(args.output / f"decision_log_{g}.csv", index=False)
    metadata = {
        "version": "V2.1", "source_commit": BASE_COMMIT, "data_mode": mode_label,
        "first_date": str(close.index[0].date()), "last_date": str(close.index[-1].date()),
        "n_stocks": args.n_stocks, "factor_lookback": 20, "calendar": "XNYS",
        "price_adjustment": "auto_adjust=True for Yahoo mode; otherwise input-defined",
        "signal": "month-end session close", "execution": "next session close",
        "returns": "gross daily equal-weight proxy; cash before first execution",
        "limitations": ["fixed universe", "no weight drift", "no transaction costs",
                        "no Sharpe/IR certification", "adjusted data not point-in-time verified"],
        "versions": {p: importlib.metadata.version(p) for p in ["numpy", "pandas", "exchange-calendars"]},
        "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in args.output.glob("*.csv")},
    }
    if args.download:
        metadata["versions"]["yfinance"] = importlib.metadata.version("yfinance")
        metadata["requested_start_inclusive"] = args.start
        metadata["requested_end_exclusive"] = args.end
    (args.output / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(mode_label)
    print("V2.1 TIMING VALIDATION ONLY: GROSS proxy, no transaction-cost or Sharpe claim.")
    print(result.decision_log.to_string(index=False))
    print(f"Saved diagnostics to {args.output.resolve()}")


if __name__ == "__main__":
    main()
