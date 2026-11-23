# Research design

## 1. Questions and comparison logic

The volume audit separates three mechanisms that can be conflated in a profitable backtest:

1. Changes in stock membership.
2. Rebalancing an otherwise fixed list.
3. Price appreciation of the selected stocks.

`dynamic_volume`, `static_monthly`, and `static_buy_hold` share the first valid signal, initial selection, and execution date. The universe benchmark starts on that same execution date. Before entry, the accounts hold cash at zero interest.

The dynamic-versus-static-monthly comparison holds the intended rebalancing frequency fixed while allowing membership to differ. The static-monthly-versus-buy-and-hold comparison holds initial membership fixed while changing the rebalancing rule. Result differences still incorporate the resulting holding paths, fees, and compounding; they are not causal estimates of independent alpha.

Implementation: [`static_controls` and `run_audit`](../multifactor/audit.py).

## 2. Signal definitions

Let $P_{i,t}$ denote the accounting price of stock $i$ on session $t$, $V_{i,t}$ its reported share volume, and $r_{i,t}=P_{i,t}/P_{i,t-1}-1$.

| Signal | Default raw definition |
|---|---|
| Momentum | $P_{i,t}/P_{i,t-20}-1$ |
| Negative volatility | $-\sqrt{252}\,\mathrm{SD}(r_{i,t-19},\ldots,r_{i,t})$ |
| Log share volume | $\log(1+\mathrm{mean}(V_{i,t-19},\ldots,V_{i,t}))$ |
| Short-term reversal | $-(P_{i,t}/P_{i,t-5}-1)$ |

For each date, each signal is clipped at its cross-sectional mean plus or minus three sample standard deviations, then standardized across stocks. Missing observations are not implicitly filled. A constant observable cross-section carries zero ranking information. The composite gives equal weight to the four processed signals and requires all four to be available.

The audit focuses on the volume signal. The broader factor comparison is available in [`validation.analyze`](../multifactor/validation.py). Share volume is not turnover relative to shares outstanding.

Implementation: [`signals.py`](../multifactor/signals.py).

## 3. Timing

The schedule is defined using the XNYS exchange calendar:

| Event | Information and account treatment |
|---|---|
| Month-end session close, $T$ | Compute the signal and select eligible stocks |
| Next session close, $E$ | Mark existing positions to that close; execute the new target and charge fees |
| Session after $E$ | First close-to-close price return earned by the new positions |

Calendar validation checks for missing sessions and does not treat an omitted observation as an exchange holiday. A partial final month does not become an artificial month-end signal.

An execution-day return can contain the price movement of old holdings and the new trading fees. It must not assign the price movement before execution to the newly selected holdings.

## 4. Self-financing accounting

The account holds fractional units, with no leverage or short positions. Position units stay fixed between orders, so market-value weights drift with prices.

At an execution close, let $h_i$ be each existing position's market value, $C$ cash, $w_i$ the target weights, and $k$ the fee rate. Pre-trade equity is:

$$
V=\sum_i h_i+C.
$$

The rebalancing solver finds post-cost equity $x$ satisfying:

$$
x+k\sum_i|w_i x-h_i|=V.
$$

Post-trade risky-asset values are $w_i x$; any unallocated fraction remains in cash. The default $k=0.001$ corresponds to 10 bps on each buy or sell notional. It is an assumption, not an estimated all-in execution cost.

The implementation records units, weights before and after trading, traded notional, fees, cash, account equity, and reconciliation residuals. The daily net return is post-trade equity divided by the previous day's post-trade equity minus one.

Adjusted input prices imply synthetic adjusted-price units, not literal brokerage share counts. There is no separate dividend cash flow, zero interest on cash, and no forced liquidation at the sample end.

Implementation: [`solve_rebalance` and `simulate_account`](../multifactor/accounting.py).

## 5. Stock-level P&L attribution

For stock $i$ and session $t$:

$$
\mathrm{GrossPnL}_{i,t}
=q_{i,t-1}(P_{i,t}-P_{i,t-1}),
$$

$$
\mathrm{NetPnL}_{i,t}
=\mathrm{GrossPnL}_{i,t}-\mathrm{Fee}_{i,t}.
$$

The calculation uses the previous close's units, including on a rebalance day. Summing across stocks reconciles to the change in account equity. Summing each stock's net P&L over the sample and dividing by initial equity gives an additive contribution to total simple return.

These contributions are not additive CAGR, risk contributions, or independently identified alpha. A stock's fraction of total net profit also has a different denominator from its contribution to total account return.

The implementation checks both daily and whole-period reconciliation. Mark-to-market unrealized P&L is included.

Implementation: [`attribution`](../multifactor/audit.py).

## 6. Leave-one-out and definition checks

### Leave-one-out

Each stock in the input universe is removed in turn. The remaining cross-section is standardized again, selections are recomputed, and the account is rerun with the same number of selected stocks. Each rerun has a benchmark that excludes the same stock.

This experiment measures sensitivity to the investable universe. It is not equivalent to subtracting the removed stock's contribution from the original account: the other holdings, fees, and compounding can change.

At least `n_stocks + 1` input stocks are required. The audit does not silently lower the portfolio size when that condition fails.

### Volume definitions

The main score uses reported share volume. An optional alternative uses:

$$
\log\left(1+\mathrm{mean}_{20}(\mathrm{source\_close}\times\mathrm{volume})\right).
$$

This is a provider-basis dollar-activity proxy, not verified transaction-level traded dollars. It is omitted when `source_close` is absent.

A separate stress check multiplies each stock's full volume series by two and counts selection changes. This exposes sensitivity to stock-specific volume units. It is not a split adjustment or an alternative optimized strategy.

The split table summarizes supplied split events and nearby volume observations. It does not infer a causal split effect or repair vendor adjustments. True float turnover is not computed because historical float and publication timestamps have not been verified.

## 7. Factor and performance diagnostics

Rank IC compares the signal-date ranking with forward returns from execution close $E$ to the close 20 sessions later. Labels are used for retrospective evaluation, not stock selection. Unmatured labels are omitted. Ties use average ranks, and constant or insufficient cross-sections yield missing correlations.

ICIR is the mean IC divided by its sample standard deviation, without annualization. It is a descriptive ratio rather than an independent-sample significance test. Factor correlations compare contemporaneous signals with each other.

For daily net returns, the performance conventions are:

- **CAGR:** compounded return annualized using 252 sessions per year.
- **Volatility:** daily sample standard deviation multiplied by $\sqrt{252}$.
- **Sharpe:** arithmetic mean daily return divided by its sample standard deviation, multiplied by $\sqrt{252}$; the risk-free rate is zero.
- **Information ratio:** annualized arithmetic active return divided by annualized tracking error against the named universe benchmark.
- **Maximum drawdown:** minimum decline from the running NAV peak, including initial NAV of one.

The audit reports full-sample and calendar-year summaries. Factor-validation period labels are chronological retrospective slices, not proof of an untouched out-of-sample evaluation. Monthly forward labels may overlap, and annualized ratios depend on time-series assumptions.

## 8. Interpretation boundary

The fixed stock universe, vendor adjustment basis, close-fill assumptions, and simple fee model remain material limitations. Delisting treatment, spreads, impact, capacity, settlement, and lot-size constraints are not fully modeled.

Implementation tests can detect accounting and timing errors under their test cases. They cannot certify point-in-time universe membership, make a retrospectively inspected sample untouched, or establish future profitability. A useful result can therefore be a narrower explanation of a backtest, including evidence that a proposed mechanism contributes little.
