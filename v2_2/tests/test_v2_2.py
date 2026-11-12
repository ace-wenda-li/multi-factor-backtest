"""Offline accounting and causality tests; synthetic data only."""
import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from backtest_v2_2 import (
    backtest, combine_factors, compute_factors, demo_data, layered_backtest,
    make_targets, preprocess_factors, simulate_account, solve_rebalance,
)
import exchange_calendars as xcals


def sessions(start="2024-01-29", end="2024-03-06"):
    return xcals.get_calendar("XNYS", start="2023-12-01", end="2024-07-15").sessions_in_range(start, end)


def inputs(end="2024-03-06"):
    index = sessions(end=end)
    close = pd.DataFrame(100., index=index, columns=["A", "B"])
    score = pd.DataFrame({"A": 2., "B": 1.}, index=index)
    return close, score


def factor(close, volume):
    return combine_factors(preprocess_factors(compute_factors(close, volume)))


def test_first_buy_is_one_sided_and_funded_from_cash():
    r = solve_rebalance([0., 0.], 1000., [0.5, 0.5], 10)
    assert r.values_after.sum() == pytest.approx(1000 / 1.001)
    assert r.fees_by_asset.sum() == pytest.approx(1000 - 1000 / 1.001)
    assert r.cash_after == pytest.approx(0, abs=1e-10)
    assert (r.trades > 0).all()


def test_complete_switch_charges_sell_and_buy_actual_values():
    r = solve_rebalance([1000., 0.], 0., [0., 1.], 10)
    expected = 1000 * .999 / 1.001
    assert r.values_after[1] == pytest.approx(expected)
    assert r.trades[0] == -1000
    assert r.fees_by_asset.sum() == pytest.approx(.001 * (1000 + expected))


def test_same_names_drift_rebalance_has_nonzero_cost():
    r = solve_rebalance([600., 400.], 0., [.5, .5], 10)
    np.testing.assert_allclose(r.values_after, [499.9, 499.9])
    np.testing.assert_allclose(r.trades, [-100.1, 99.9])
    assert r.fees_by_asset.sum() == pytest.approx(.2)


def test_already_at_target_makes_no_trade():
    r = solve_rebalance([500., 500.], 0., [.5, .5], 10)
    np.testing.assert_array_equal(r.trades, [0, 0])
    np.testing.assert_array_equal(r.fees_by_asset, [0, 0])


def test_liquidation_is_one_sided_and_no_rebuy():
    r = solve_rebalance([600., 400.], 0., [0., 0.], 10)
    assert r.cash_after == pytest.approx(999.)
    assert r.fees_by_asset.sum() == pytest.approx(1.)
    np.testing.assert_array_equal(r.values_after, [0., 0.])


def test_cash_target_and_no_borrowing():
    r = solve_rebalance([0., 0.], 1000., [.5, 0.], 10)
    after = 1000 / 1.0005
    assert r.values_after[0] == pytest.approx(after / 2)
    assert r.cash_after == pytest.approx(after / 2)


@pytest.mark.parametrize("fee", [-1., np.nan, np.inf, 10000.])
def test_invalid_fees_rejected(fee):
    with pytest.raises(ValueError, match="cost_bps"):
        solve_rebalance([0.], 1000., [1.], fee)


@pytest.mark.parametrize("target", [[-0.1, .5], [.6, .6], [np.nan, 0.], [np.inf, 0.]])
def test_short_leveraged_or_nonfinite_target_rejected(target):
    with pytest.raises(ValueError, match="Target"):
        solve_rebalance([500., 500.], 0., target)


@pytest.mark.parametrize("seed", range(8))
def test_random_portfolios_obey_budget_and_exact_target(seed):
    rng = np.random.default_rng(seed)
    for _ in range(30):
        h = rng.uniform(0, 1e5, 10)
        cash = float(rng.uniform(0, 1e5))
        w = rng.dirichlet(np.ones(10)) * rng.uniform(.05, 1)
        bps = float(rng.uniform(0, 100))
        r = solve_rebalance(h, cash, w, bps)
        pre = h.sum() + cash
        post = r.values_after.sum() + r.cash_after
        assert post + r.fees_by_asset.sum() == pytest.approx(pre, rel=1e-12)
        np.testing.assert_allclose(r.values_after / post, w, rtol=1e-11)
        np.testing.assert_allclose(r.fees_by_asset, abs(r.trades) * bps / 10000)
        assert r.cash_after == pytest.approx(cash - r.trades.sum() - r.fees_by_asset.sum(), abs=1e-7)
        assert r.cash_after >= 0


def test_entry_day_gets_cost_but_not_pre_entry_jump():
    close, scores = inputs("2024-02-05")
    close.loc["2024-02-01", "A"] = 200.
    close.loc["2024-02-02":, "A"] = 220.
    r = backtest(close, scores, n_stocks=1, initial_cash=1000.)
    assert r.daily.loc["2024-02-01", "gross_return_on_net_holdings"] == 0.
    assert r.daily.loc["2024-02-01", "net_return"] == pytest.approx(1 / 1.001 - 1)
    assert r.daily.loc["2024-02-02", "net_return"] == pytest.approx(.1)
    assert r.daily.loc["2024-02-02", "fees"] == 0.


def test_fixed_units_drift_and_differ_from_daily_equal_weight_proxy():
    close, scores = inputs("2024-02-05")
    close.loc["2024-02-02":, "A"] = 200.
    close.loc["2024-02-05", "B"] = 200.
    r = backtest(close, scores, n_stocks=2, cost_bps=0, initial_cash=1000.)
    np.testing.assert_allclose(r.weights_after_close.loc["2024-02-02"], [2/3, 1/3])
    assert r.daily.loc["2024-02-02", "net_return"] == pytest.approx(.5)
    assert r.daily.loc["2024-02-05", "net_return"] == pytest.approx(1/3)
    assert r.daily.equity_after_trade.iloc[-1] == pytest.approx(2000.)
    np.testing.assert_allclose(r.units_after_close.loc["2024-02-01":], 5.)
    assert len(r.trades) == 2  # Initial buys only; no hidden daily reset.


def test_same_selection_monthly_rebalance_trades_drifted_weights():
    close, scores = inputs()
    close.loc["2024-02-02":, "A"] = 150.
    r = backtest(close, scores, n_stocks=2, initial_cash=1000.)
    np.testing.assert_allclose(r.weights_before_trade.loc["2024-03-01"], [.6, .4])
    np.testing.assert_allclose(r.weights_after_close.loc["2024-03-01"], [.5, .5])
    assert r.daily.loc["2024-03-01", "fees"] > 0
    assert r.daily.loc["2024-02-02":"2024-02-29", "fees"].sum() == 0


def test_switch_day_pnl_uses_old_holdings_then_charges_cost():
    close, scores = inputs()
    scores.loc["2024-02-29", ["A", "B"]] = [0., 3.]
    close.loc["2024-03-01":, "A"] = 110.
    close.loc["2024-03-01", "B"] = 200.
    close.loc["2024-03-04":, "B"] = 220.
    r = backtest(close, scores, n_stocks=1, initial_cash=1000.)
    day = r.daily.loc["2024-03-01"]
    assert day.gross_return_on_net_holdings == pytest.approx(.1)
    assert day.net_return == pytest.approx(1.1 * .999 / 1.001 - 1)
    assert r.daily.loc["2024-03-04", "net_return"] == pytest.approx(.1)


def test_skip_signal_keeps_units_without_reset():
    close, scores = inputs()
    close.loc["2024-02-02":, "A"] = 150.
    scores.loc["2024-02-29"] = np.nan
    r = backtest(close, scores, n_stocks=2)
    np.testing.assert_allclose(r.units_after_close.loc["2024-03-01"], r.units_after_close.loc["2024-02-01"])
    assert r.daily.loc["2024-03-01", "fees"] == 0
    assert r.decisions.iloc[-1].status == "skipped_insufficient_factors"


def test_no_signal_means_cash_and_no_fees():
    close, scores = inputs("2024-01-31")
    r = backtest(close, scores, n_stocks=1, initial_cash=1000.)
    assert (r.daily.equity_after_trade == 1000).all()
    assert (r.daily.net_return == 0).all()
    assert r.trades.empty


def test_final_execution_pays_fee_without_forced_terminal_exit():
    close, scores = inputs("2024-02-01")
    r = backtest(close, scores, n_stocks=1, initial_cash=1000.)
    assert r.daily.equity_after_trade.iloc[-1] == pytest.approx(1000 / 1.001)
    assert len(r.trades) == 1
    assert r.units_after_close.iloc[-1, 0] > 0


def test_final_holding_period_included():
    close, scores = inputs("2024-02-15")
    close.iloc[-1, 0] = 110.
    r = backtest(close, scores, n_stocks=1, cost_bps=0, initial_cash=1000.)
    assert r.daily.equity_after_trade.iloc[-1] == pytest.approx(1100.)
    assert r.daily.index.equals(close.index)


@pytest.mark.parametrize("date", ["2024-02-01", "2024-02-02"])
def test_selected_or_held_missing_price_raises(date):
    close, scores = inputs("2024-02-05")
    close.loc[date, "A"] = np.nan
    with pytest.raises(ValueError, match="missing/invalid"):
        backtest(close, scores, n_stocks=1)


def test_unheld_missing_prices_do_not_poison_account():
    close, scores = inputs("2024-02-05")
    close["B"] = np.nan
    r = backtest(close, scores, n_stocks=1)
    assert np.isfinite(r.daily.equity_after_trade).all()


def test_partial_order_row_is_rejected():
    close, _ = inputs("2024-02-05")
    target = close * np.nan
    target.loc["2024-02-01", "A"] = .5
    with pytest.raises(ValueError, match="An order"):
        simulate_account(close, target)


def test_explicit_zero_target_liquidates_and_stays_cash():
    close, _ = inputs("2024-02-05")
    target = close * np.nan
    target.loc["2024-02-01"] = [1., 0.]
    target.loc["2024-02-02"] = [0., 0.]
    r = simulate_account(close, target, initial_cash=1000.)
    assert r.daily.cash_after.iloc[-1] == pytest.approx(1000 * .999 / 1.001)
    assert (r.units_after_close.loc["2024-02-02":] == 0).all().all()
    assert r.trades.side.tolist() == ["BUY", "SELL"]


def test_daily_ledger_matches_trades_and_compounded_nav():
    close, volume = demo_data()
    r = backtest(close, factor(close, volume))
    grouped = r.trades.groupby("date").fee.sum().reindex(close.index, fill_value=0.)
    np.testing.assert_allclose(grouped, r.daily.fees)
    np.testing.assert_allclose(r.daily.equity_after_trade, 1e6 * (1 + r.daily.net_return).cumprod())
    np.testing.assert_allclose(r.daily.equity_before_trade, r.daily.equity_after_trade + r.daily.fees)
    np.testing.assert_allclose(r.daily.fees, .001 * (r.daily.buy_notional + r.daily.sell_notional))
    np.testing.assert_allclose(r.daily.traded_fraction, (r.daily.buy_notional + r.daily.sell_notional) / r.daily.equity_before_trade)
    np.testing.assert_allclose(r.daily.net_return, r.daily.gross_return_on_net_holdings - r.daily.fees / r.daily.equity_previous)
    assert (r.daily.cash_after >= 0).all()
    assert (r.units_after_close >= 0).all().all()
    assert (r.weights_after_close.sum(axis=1) <= 1 + 1e-10).all()


def test_zero_cost_reference_really_has_zero_fees():
    close, volume = demo_data()
    scores = factor(close, volume)
    gross = backtest(close, scores, cost_bps=0)
    net = backtest(close, scores, cost_bps=10)
    assert (gross.daily.fees == 0).all()
    assert (net.daily.equity_after_trade <= gross.daily.equity_after_trade + 1e-7).all()


def test_future_perturbation_cannot_change_earlier_accounting():
    close, volume = demo_data()
    cutoff = pd.Timestamp("2024-03-15")
    c2, v2 = close.copy(), volume.copy()
    c2.loc[c2.index > cutoff] *= np.linspace(1, 100, close.shape[1])
    v2.loc[v2.index > cutoff] *= 1e6
    a, b = backtest(close, factor(close, volume)), backtest(c2, factor(c2, v2))
    assert_frame_equal(a.daily.loc[:cutoff], b.daily.loc[:cutoff])
    assert_frame_equal(a.units_after_close.loc[:cutoff], b.units_after_close.loc[:cutoff])


def test_prefix_and_full_history_accounting_match():
    close, volume = demo_data()
    cutoff = pd.Timestamp("2024-03-15")
    a = backtest(close, factor(close, volume))
    c, v = close.loc[:cutoff], volume.loc[:cutoff]
    b = backtest(c, factor(c, v))
    assert_frame_equal(a.daily.loc[:cutoff], b.daily)
    assert_frame_equal(a.units_after_close.loc[:cutoff], b.units_after_close.loc[:cutoff])


def test_quintiles_share_accounting_and_next_close_timing():
    idx = sessions(end="2024-02-05")
    names = [f"S{i:02d}" for i in range(10)]
    close = pd.DataFrame(100., index=idx, columns=names)
    scores = pd.DataFrame(np.tile(np.arange(10.), (len(idx), 1)), index=idx, columns=names)
    close.loc["2024-02-01", names[-2:]] = 200.
    close.loc["2024-02-02":, names[-2:]] = 220.
    layers = layered_backtest(close, scores)
    r = layers["Q5"]
    assert r.daily.loc["2024-02-01", "net_return"] == pytest.approx(1 / 1.001 - 1)
    assert r.daily.loc["2024-02-02", "net_return"] == pytest.approx(.1)
    assert_frame_equal(r.daily, backtest(close, scores, n_stocks=2).daily)


def test_v21_and_v22_use_identical_signal_selection_and_schedule():
    from backtest_v2_1 import backtest as old_backtest
    close, volume = demo_data()
    scores = factor(close, volume)
    old, new = old_backtest(close, scores), backtest(close, scores)
    assert_frame_equal(old.schedule, new.schedule)
    cols = ["signal_date", "execution_date", "first_return_date", "n_eligible", "selected"]
    assert_frame_equal(old.decision_log[cols], new.decisions[cols])


def test_quantile_ties_keep_cash_not_arbitrary_grouping():
    close, _ = demo_data()
    layers = layered_backtest(close, close * 0 + 1)
    for r in layers.values():
        assert (r.daily.net_return == 0).all()
        assert r.trades.empty


def test_whole_missing_session_is_rejected():
    close, score = inputs("2024-02-05")
    close = close.drop(pd.Timestamp("2024-02-01"))
    with pytest.raises(ValueError, match="Missing sessions"):
        backtest(close, score.loc[close.index], n_stocks=1)
