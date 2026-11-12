# V2.1 GitHub publication validation

Date: 2026-11-12. Reference: `ace-wenda-li/multi-factor-backtest` commit `9f8b17e8e451aca45afe98a3a1cdd9729056e9d2`.

## Executed checks

- **31 offline pytest cases passed** in the local validation environment. See `pytest_output.txt`. This is a locally executed test result, not a GitHub Actions status.
- Standalone synthetic-data CLI demo completed.
- Local CSV replay completed; `gross_returns.csv`, `weights_after_close.csv`, `weights_for_return.csv` and `quintile_gross_returns.csv` agreed within absolute and relative tolerance 1e-12.
- Core source, full test file and direct-dependency list match the previously delivered archive byte for byte. Git blob identities were compared with the uploaded tree. Hashes are recorded in `../SOURCE_MANIFEST.json`.

Tests cover cross-sectional scaling/winsorization, future-perturbation invariance, truncated-history invariance, weekend and holiday month ends, missing sessions, incomplete final months, next-close execution, old-position attribution on rebalance dates, final-interval retention, invalid signal handling, missing selected/held prices, quintile timing, and refusal to use the old nonzero cost calculation.

## Environment

Python 3.13.5, Linux; numpy 2.3.5, pandas 2.2.3, exchange-calendars 4.13.1, pytest 9.0.2.

## Limits

No Yahoo historical download or full real-market backtest was run. No revised Sharpe, information ratio or net performance is certified. The user's macOS/Python 3.11 environment was not executed here. Weight drift, transaction costs, survivorship bias and complete point-in-time market-data validation remain unresolved. Direct dependencies are pinned, not the full transitive environment.

All demo inputs are synthetic. Generated CSVs are intentionally not committed in this delivery; run `--demo` to produce them locally in a new output directory. Documentation and validation logs were refreshed for publication, while core code and tests are unchanged.

## Publication boundary

Delivery is confined to the new `fix/v2.1-timing` branch: `v2_1/` and `V2_1_START_HERE.md`. Original root files are preserved; main is not updated and no merge is performed. Original performance figures in the root README do not describe this version.
