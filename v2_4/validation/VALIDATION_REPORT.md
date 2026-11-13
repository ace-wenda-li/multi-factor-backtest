# V2.4 validation report

Date: 2026-11-13. Environment: Linux, CPython 3.13.5, numpy 2.3.5, pandas 2.2.3, exchange-calendars 4.13.1, pytest 9.0.2.

## Executed

- `python -m pytest -q tests ../v2_1/tests`: **67 passed in 7.51s** in the final local test run (36 V2.4 tests, 31 unchanged V2.1 tests).
- Earlier full offline demo followed by a fresh CSV snapshot replay succeeded. All **53 CSV files** matched at `rtol=1e-10, atol=1e-7`. Metadata source strings and run timestamps intentionally differ.
- Exact old-engine blob checks passed: V2.1 `b940174681ed6527fb8624c06727b768a288bf83`; V2.2 `fcc5dc2514791d1f131c3f2631f00e87378f4bf1`.
- Synthetic demo per-stock-to-account daily P&L reconciliation maximum absolute residual: `2.992237568832934e-10` on initial capital 1,000,000.
- Tests cover causal frozen names, initial buy versus switch-day P&L, exact fee attribution, daily and total P&L reconciliation, no implicit daily rebalancing in buy-and-hold, no terminal liquidation, all-name leave-one-out, optional provider-dollar proxy, missing-input refusal, no overwrite, reference mismatch detection, snapshot hashes, input-frame nonmutation, and mocked Yahoo response extraction.

## Scope and limitations

The complete V2.2 and V2.3 historical test suites were retained in Git but were not re-executed in this local test command. V2.4 compares the dynamic account directly against the unchanged V2.2 implementation. Mac/Python3.11 still requires user verification.

No real Yahoo request or 2018–2024 historical audit run was performed here. Network adapter tests are mock-only. No genuine historical float turnover, point-in-time universe, adjusted-data verification, independent holdout, or live execution validation is claimed.

Files are added only under v2_4 plus V2_4_START_HERE.md; all inherited version files are unchanged. Source blob being published: f038a184a3de6e06a421593d7765158b52698713.
