# Multi-Factor Equity Research

**A reproducible study of equity signals, portfolio accounting, and the sources of backtest performance.**

The central question is whether a volume-ranked portfolio's results come from changing its stock selection, rebalancing a persistent set of stocks, or simply holding those stocks. The project compares these mechanisms using a shared execution schedule and transaction-cost model, then reconciles portfolio returns to stock-level profit and loss.

**Start with the [research notebook](notebooks/Factor_Audit.ipynb).** It contains an offline synthetic walkthrough, the control portfolios, diagnostic tables, and interpretation. The demonstration verifies the research workflow; its returns are not market evidence.

## Research design

| Portfolio | Selection and holdings | Question |
|---|---|---|
| Dynamic volume | Select the top 10 volume scores each month; rebalance to equal weights | What happens when membership can change? |
| Fixed-list monthly | Freeze the first valid selection; rebalance those names monthly | What is the incremental result of changing membership? |
| Fixed-list buy-and-hold | Use the same initial selection; hold units after entry | How does periodic rebalancing change the outcome? |
| Universe equal-weight | Rebalance the full fixed universe monthly | How does the strategy compare with a simple matched-universe benchmark? |

The main controls enter on the same execution date. The fixed list is selected at that initial signal, rather than chosen from later winners.

## Implementation

- **Signals:** 20-session momentum, negative volatility, log average share volume, and short-term reversal; cross-sectional clipping and standardization on each date.
- **Timing:** month-end close signals, next-session close execution, and explicit attribution of returns to the holdings that existed before the price move.
- **Accounting:** fixed position units between trades, drifting weights, cash balances, and proportional fees on actual buy and sell notional. Target weights are defined on post-cost equity.
- **Diagnostics:** Rank IC, factor correlations, benchmark-relative performance, stock-level P&L, leave-one-out reruns, and volume-definition checks.
- **Reproducibility:** saved input snapshots, parameters, environment versions, output hashes, and refusal to overwrite an existing run directory.

The methods are documented in [Research design](docs/RESEARCH.md); input conventions and limitations are in [Data](docs/DATA.md).

## Run the notebook

Use Python 3.11 or later in a project environment. From the repository root:

```bash
python -m pip install -e ".[notebook,test]"
python -m jupyter lab notebooks/Factor_Audit.ipynb
```

Keep the notebook in `demo` mode for the first run. It requires no market-data account or download. Each save creates a separate output directory.

Optional command-line execution:

```bash
python -m multifactor.audit --demo --output outputs/demo_001
python -m pytest -q
```

Choose a new output name for each command-line run. For an existing input snapshot, use `--csv-dir path/to/snapshot` instead of `--demo`. Market downloads are an explicit optional mode described in [Data](docs/DATA.md).

## Repository map

| Path | Purpose |
|---|---|
| [`notebooks/Factor_Audit.ipynb`](notebooks/Factor_Audit.ipynb) | Main research walkthrough |
| [`multifactor/signals.py`](multifactor/signals.py) | Factor construction, preprocessing, and exchange-session scheduling |
| [`multifactor/accounting.py`](multifactor/accounting.py) | Self-financing account simulation and trade records |
| [`multifactor/validation.py`](multifactor/validation.py) | Single-factor and composite diagnostics |
| [`multifactor/audit.py`](multifactor/audit.py) | Controlled comparisons, attribution, sensitivity checks, and snapshot export |
| [`tests/`](tests/) | Regression tests for timing, accounting, data checks, and diagnostics |

## Evidence and scope

The [validation record](docs/VALIDATION.md) documents 123 passing tests and an unchanged set of 53 CSV exports after consolidating the research code. The notebook includes a rendered synthetic example.

The repository provides executable examples and tests of the implementation. Tests cover causal timing, fee accounting, reconciliation, static controls, data alignment, and changes to future observations. A passing suite supports those tested properties; it does not validate the historical universe or certify a trading edge.

Market analysis uses a fixed 30-stock US universe with survivorship bias. Adjusted-price units, idealized closing fills, an assumed 10 bps fee per buy or sell notional, and incomplete historical data provenance limit the interpretation of returns. The research questions were developed retrospectively; no untouched holdout or live performance is claimed.

This project emphasizes traceable calculations, meaningful controls, and interpretation of results under stated assumptions.
