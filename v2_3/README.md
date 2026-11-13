# V2.3 — Factor Efficacy & Retrospective Performance Research

**Standalone directory `v2_3/` on `fix/v2.3-factor-validation`. V1, V2.1, V2.2 and main are unchanged.**

This research diagnostic reuses the V2.1 signal/data logic and V2.2 net-of-assumed-cost account implementation, without modifying those versions.

### Pre-defined hypotheses

Four cross-sectionally normalized factors: 20-session momentum, negative 20-session volatility, log of average 20-session **share volume** (not true turnover), negative 5-session return (reversal). The composite is an equal 25%-weight score, selects the top ten names at month-end close, and trades at the following session close. Benchmark is an **equal-weight portfolio of the same fixed universe** (monthly reset, same fee assumption), not SPY. Each single-factor strategy uses the same ten-name selection and execution.

### IC and timing

Rank IC compares the **month-end signal** to stock returns from **next-session execution close** to the close 20 sessions later, with contemporaneous cross-sectional Spearman correlations and pairwise missing-value exclusion. Never use label prices to select the portfolio. Late labels are omitted, not assumed zero. Monthly signals and future 20-day outcomes can overlap. ICIR = mean IC / sample IC standard deviation (unannualized descriptive ratio); no unsupported t-stats or p-values. Factor correlations are contemporaneous across stocks, not future returns.

### Retrospective slices, NOT pristine out-of-sample

- Train: through 2021-12-31.
- Validation: 2022-01-01 through 2022-12-31.
- Test: 2023-01-01 through 2024-12-31.
- IC records are only allocated where both signal and outcome date lie within that slice.
- Daily portfolio returns are sliced by realized date from the V2.2 account. Factor weights are never refitted.

**These periods were already examined during earlier research. They are retrospective chronological descriptions, NOT a genuinely untouched test.**

### Performance definitions

- Returns are V2.2 actual long-only account **daily net returns**, with assumed 10bps on each actual buy/sell notional; cash yields zero.
- CAGR is geometrically compounded annual return.
- Sharpe assumes zero risk-free rate: arithmetic daily mean × sqrt(252) / daily sample SD.
- Annual active return is 252 × mean daily (strategy minus benchmark), **not the CAGR difference**.
- IR is annualized active return divided by annualized tracking error; zero TE yields missing value.
- Max drawdown includes starting NAV = 1.

### Limitations

A fixed 30-name current-biased US universe, unverified point-in-time historical corporate actions, idealized next-close fills, synthetic/adjusted-price share units, no spread/impact/capacity, and retrospective model scrutiny mean the results are **not independently validated alpha**. The 10bps cost is an assumption, not calibration. No new optimized trading rule was created.

### Mac SOP (new separate folder)

```bash
cd "$HOME/Downloads" && \
git clone --branch fix/v2.3-factor-validation --single-branch \
  https://github.com/ace-wenda-li/multi-factor-backtest.git QR_V23_separate && \
cd QR_V23_separate/v2_3 && \
uv venv --python 3.11 .venv && \
uv pip install --python .venv/bin/python -r requirements-v2_3.txt && \
.venv/bin/python -m pytest -q tests ../v2_2/tests ../v2_1/tests && \
.venv/bin/python factor_validation_v2_3.py --demo --output outputs_v23_demo
```

Open Finder with `open "$HOME/Downloads/QR_V23_separate/v2_3/outputs_v23_demo"`.

Optional CSV replay from existing V2.2 demo: `.venv/bin/python factor_validation_v2_3.py --csv-dir "$HOME/Downloads/QR_V22_separate/v2_2/outputs_v2_2_demo" --output outputs_v23_csv`.

Never overwrite nonempty output folders. Optional real-data download requires separately installed yfinance, and historical profitability is unverified.
