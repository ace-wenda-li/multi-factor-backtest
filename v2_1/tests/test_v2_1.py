"""Offline regression tests. No Yahoo access and no historical-return claims."""
import numpy as np
import pandas as pd
import pytest
import exchange_calendars as xcals
from pandas.testing import assert_frame_equal, assert_series_equal

from backtest_v2_1 import (
    backtest, combine_factors, compute_factors, demo_data, layered_backtest,
    monthly_schedule, preprocess_factors, winsorize,
)


def sessions(start="2024-01-29", end="2024-03-06"):
    cal = xcals.get_calendar("XNYS", start="2023-12-01", end="2025-01-15")
    return cal.sessions_in_range(start, end)


def two_assets(start="2024-01-29", end="2024-03-06"):
    index = sessions(start, end)
    close = pd.DataFrame(100.0, index=index, columns=["A", "B"])
    factor = pd.DataFrame({"A": 2.0, "B": 1.0}, index=index)
    return close, factor


def pipeline(close, volume):
    return combine_factors(preprocess_factors(compute_factors(close, volume)))


def test_cross_sectional_zscore_matches_hand_calculation():
    f = pd.DataFrame([[1., 2., 3.], [10., 20., 30.]],
                     index=pd.date_range("2024-01-01", periods=2), columns=list("ABC"))
    expected = pd.DataFrame([[-1., 0., 1.], [-1., 0., 1.]], index=f.index, columns=f.columns)
    assert_frame_equal(preprocess_factors({"x": f})["x"], expected)


def test_winsorization_uses_row_specific_limits():
    f = pd.DataFrame([[1., 2., 100.], [1000., 1100., 5000.]],
                     index=pd.date_range("2024-01-01", periods=2), columns=list("ABC"))
    result = winsorize(f, (-1, 1))
    for date in f.index:
        x = f.loc[date]
        np.testing.assert_allclose(result.loc[date], x.clip(x.mean() - x.std(), x.mean() + x.std()))


def test_append_extreme_future_cannot_change_past_standardization():
    f = pd.DataFrame([[1., 2., 3.], [4., 8., 9.]],
                     index=pd.date_range("2024-01-01", periods=2), columns=list("ABC"))
    future = pd.DataFrame([[1e12, -1e12, 100.]], index=[pd.Timestamp("2024-01-03")], columns=f.columns)
    short = preprocess_factors({"x": f})["x"]
    extended = preprocess_factors({"x": pd.concat([f, future])})["x"]
    assert_frame_equal(short, extended.loc[f.index], check_freq=False)


def test_old_full_sample_formula_fails_same_causality_check():
    f = pd.DataFrame([[1., 2., 3.], [4., 8., 9.]], columns=list("ABC"))
    extended = pd.concat([f, pd.DataFrame([[1e12, -1e12, 100.]], columns=f.columns)], ignore_index=True)
    old_short = (f - f.mean()) / f.std()
    old_extended = (extended - extended.mean()) / extended.std()
    assert not np.allclose(old_short, old_extended.iloc[:2])


def test_constant_cross_section_is_zero_and_missing_stays_missing():
    f = pd.DataFrame([[7., 7., np.nan]], index=[pd.Timestamp("2024-01-01")], columns=list("ABC"))
    actual = preprocess_factors({"x": f})["x"]
    np.testing.assert_array_equal(actual.iloc[0, :2], [0., 0.])
    assert np.isnan(actual.iloc[0, 2])


@pytest.mark.parametrize("row", [[np.nan, np.nan, np.nan], [1., np.nan, np.nan], [np.inf, -np.inf, np.nan]])
def test_unusable_cross_section_is_nan(row):
    f = pd.DataFrame([row], index=[pd.Timestamp("2024-01-01")], columns=list("ABC"))
    assert preprocess_factors({"x": f})["x"].isna().all().all()


def test_composite_requires_all_factor_values():
    index = pd.date_range("2024-01-01", periods=2)
    a = pd.DataFrame([[1., 2.], [3., 4.]], index=index)
    b = a.copy(); b.iloc[1, 0] = np.nan
    out = combine_factors({"a": a, "b": b})
    assert np.isnan(out.iloc[1, 0])
    assert out.iloc[0, 1] == 2.


def test_actual_month_end_when_calendar_month_ends_on_weekend():
    result = monthly_schedule(sessions("2024-06-03", "2024-07-05"))
    assert result.iloc[0].signal_date == pd.Timestamp("2024-06-28")
    assert result.iloc[0].execution_date == pd.Timestamp("2024-07-01")
    assert result.iloc[0].first_return_date == pd.Timestamp("2024-07-02")


def test_month_end_holiday_not_just_business_day_offset():
    result = monthly_schedule(sessions("2024-03-01", "2024-04-03"))
    assert result.iloc[0].signal_date == pd.Timestamp("2024-03-28")
    assert result.iloc[0].execution_date == pd.Timestamp("2024-04-01")
    assert result.iloc[0].first_return_date == pd.Timestamp("2024-04-02")


def test_incomplete_final_month_does_not_create_signal():
    result = monthly_schedule(sessions("2024-01-29", "2024-02-15"))
    assert result.signal_date.tolist() == [pd.Timestamp("2024-01-31")]


def test_final_signal_without_available_execution_is_not_traded():
    result = monthly_schedule(sessions("2024-01-29", "2024-01-31"))
    assert result.empty


def test_no_signal_means_cash_not_an_exception():
    close, scores = two_assets("2024-01-29", "2024-01-31")
    result = backtest(close, scores, n_stocks=1)
    assert (result.gross_returns == 0).all()
    assert (result.weights_after_close == 0).all().all()


def test_missing_entire_session_is_rejected_not_treated_as_holiday():
    index = sessions("2024-01-29", "2024-02-05").drop(pd.Timestamp("2024-02-01"))
    with pytest.raises(ValueError, match="Missing sessions"):
        monthly_schedule(index)


def test_duplicate_dates_rejected():
    index = sessions("2024-01-29", "2024-02-05")
    with pytest.raises(ValueError, match="unique and sorted"):
        monthly_schedule(index.append(index[-1:]))


def test_unsorted_dates_rejected():
    with pytest.raises(ValueError, match="unique and sorted"):
        monthly_schedule(sessions("2024-01-29", "2024-02-05")[::-1])


def test_entry_day_jump_cannot_be_earned_by_new_position():
    close, scores = two_assets("2024-01-29", "2024-02-05")
    close.loc["2024-02-01", "A"] = 200.
    close.loc["2024-02-02":, "A"] = 220.
    result = backtest(close, scores, n_stocks=1)
    assert result.gross_returns.loc["2024-02-01"] == 0.
    assert result.gross_returns.loc["2024-02-02"] == pytest.approx(.10)
    assert result.weights_after_close.loc["2024-02-01", "A"] == 1.
    assert result.weights_for_return.loc["2024-02-01", "A"] == 0.


def test_execution_day_return_belongs_to_old_position():
    close, scores = two_assets()
    scores.loc["2024-02-29", ["A", "B"]] = [0., 3.]
    close.loc["2024-03-01":, "A"] = 110.
    close.loc["2024-03-01", "B"] = 200.
    close.loc["2024-03-04":, "B"] = 220.
    result = backtest(close, scores, n_stocks=1)
    assert result.gross_returns.loc["2024-03-01"] == pytest.approx(.10)  # A, not B's 100% jump.
    assert result.gross_returns.loc["2024-03-04"] == pytest.approx(.10)  # B, now held.
    assert result.weights_for_return.loc["2024-03-01", "A"] == 1.
    assert result.weights_for_return.loc["2024-03-04", "B"] == 1.


def test_final_period_is_not_discarded():
    close, scores = two_assets("2024-01-29", "2024-02-15")
    close.iloc[-1, 0] = 110.
    result = backtest(close, scores, n_stocks=1)
    assert result.gross_returns.index.equals(close.index)
    assert result.gross_returns.iloc[-1] == pytest.approx(.10)


def test_invalid_new_signal_keeps_existing_holdings():
    close, scores = two_assets()
    scores.loc["2024-02-29"] = np.nan
    close.loc["2024-03-01":, "A"] = 110.
    result = backtest(close, scores, n_stocks=1)
    assert result.decision_log.iloc[-1].status == "skipped_insufficient_factors"
    assert result.weights_after_close.loc["2024-03-01", "A"] == 1.
    assert result.gross_returns.loc["2024-03-01"] == pytest.approx(.10)


@pytest.mark.parametrize("bad_date", ["2024-02-01", "2024-02-02"])
def test_missing_selected_price_is_an_error_not_future_based_reselection(bad_date):
    close, scores = two_assets("2024-01-29", "2024-02-05")
    close.loc[bad_date, "A"] = np.nan
    with pytest.raises(ValueError, match="selected/held asset"):
        backtest(close, scores, n_stocks=1)


def test_weights_are_cash_or_fully_invested_without_negative_exposure():
    close, volume = demo_data()
    result = backtest(close, pipeline(close, volume), n_stocks=3)
    sums = result.weights_after_close.sum(axis=1)
    assert (np.isclose(sums, 0.) | np.isclose(sums, 1.)).all()
    assert (result.weights_after_close >= 0).all().all()
    assert result.gross_returns.index.is_unique


def test_preprocessing_and_trades_are_invariant_to_future_perturbation():
    close, volume = demo_data()
    cutoff = pd.Timestamp("2024-03-15")
    changed_close, changed_volume = close.copy(), volume.copy()
    changed_close.loc[changed_close.index > cutoff] *= np.linspace(1., 100., close.shape[1])
    changed_volume.loc[changed_volume.index > cutoff] *= 1e6
    f1, f2 = pipeline(close, volume), pipeline(changed_close, changed_volume)
    assert_frame_equal(f1.loc[:cutoff], f2.loc[:cutoff])
    a, b = backtest(close, f1, n_stocks=3), backtest(changed_close, f2, n_stocks=3)
    assert_frame_equal(a.weights_after_close.loc[:cutoff], b.weights_after_close.loc[:cutoff])
    assert_series_equal(a.gross_returns.loc[:cutoff], b.gross_returns.loc[:cutoff])


def test_full_history_and_truncated_history_match_before_cutoff():
    close, volume = demo_data()
    cutoff = pd.Timestamp("2024-03-15")
    full = backtest(close, pipeline(close, volume), n_stocks=3)
    short_c, short_v = close.loc[:cutoff], volume.loc[:cutoff]
    short = backtest(short_c, pipeline(short_c, short_v), n_stocks=3)
    assert_series_equal(full.gross_returns.loc[:cutoff], short.gross_returns)
    assert_frame_equal(full.weights_after_close.loc[:cutoff], short.weights_after_close)


def test_quintiles_obey_same_next_close_rule():
    index = sessions("2024-01-29", "2024-02-05")
    names = [f"S{i:02d}" for i in range(10)]
    close = pd.DataFrame(100., index=index, columns=names)
    scores = pd.DataFrame(np.tile(np.arange(10, dtype=float), (len(index), 1)), index=index, columns=names)
    close.loc["2024-02-01", names[-2:]] = 200.
    close.loc["2024-02-02":, names[-2:]] = 220.
    result = layered_backtest(close, scores)
    assert result["Q5"].gross_returns.loc["2024-02-01"] == 0.
    assert result["Q5"].gross_returns.loc["2024-02-02"] == pytest.approx(.10)
    assert_frame_equal(result["Q5"].schedule, backtest(close, scores, 2).schedule)


def test_duplicate_quantile_edges_skip_without_silent_unequal_groups():
    index = sessions("2024-01-29", "2024-02-05")
    close = pd.DataFrame(100., index=index, columns=[f"S{i}" for i in range(10)])
    scores = close * 0 + 1.
    result = layered_backtest(close, scores)
    assert result["Q1"].decision_log.iloc[0].status == "skipped_duplicate_quantile_edges"
    assert (result["Q1"].gross_returns == 0).all()


def test_nonzero_legacy_cost_is_explicitly_blocked():
    close, scores = two_assets()
    with pytest.raises(ValueError, match="GROSS"):
        backtest(close, scores, n_stocks=1, cost_bps=10)


def test_factor_computation_does_not_forward_fill_missing_price():
    close, volume = demo_data()
    close.iloc[30, 0] = np.nan
    factors = compute_factors(close, volume)
    assert np.isnan(factors["volatility"].iloc[31, 0])
    assert np.isnan(factors["momentum"].iloc[30, 0])


def test_two_stock_gross_proxy_matches_manual_weighted_return():
    close, scores = two_assets("2024-01-29", "2024-02-05")
    close.loc["2024-02-02":, ["A", "B"]] = [110., 80.]
    result = backtest(close, scores, n_stocks=2)
    assert result.gross_returns.loc["2024-02-02"] == pytest.approx(-.05)
    assert result.gross_returns.loc["2024-02-05"] == 0.
