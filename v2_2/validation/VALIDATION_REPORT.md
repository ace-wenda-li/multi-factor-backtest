# V2.2 validation report

Validation date: 2026-11-12.
Environment: Linux / Python 3.13.5. Not yet tested on the user's Mac.

## Executed checks
- `python -m pytest -q tests ../v2_1/tests`: 74 passed (43 new + 31 unchanged V2.1).
- `python backtest_v2_2.py --demo`: successful synthetic-data run.
- CSV replay: all 60 CSV outputs matched at atol=1e-9, rtol=1e-11.
- Existing output directory: rejected with exit code 2 before writing.
- Main-account daily self-financing residual: maximum 3.748e-10, on initial equity 1,000,000.

## Synthetic demonstration only
Initial equity: 1,000,000.000000.
Ending equity with assumed 10 bps per buy/sell notional: 1,041,866.651536.
Ending equity of separately simulated zero-cost account: 1,044,012.476605.
Total cash fees paid: 2,096.790090.
These numbers are not historical market performance. The ending-equity gap need not equal the sum of fees because of compounding.

## Preservation
Read-only reuse of V2.1 core blob b940174681ed6527fb8624c06727b768a288bf83.
V2.1 test blob fdf161054981c2757b413a80af6db0b348756436 and dependency blob 86746f3844bfd9e5e2a0259d940516024e958de7 match the inspected repository.
No V1/V2.1 source or existing output was edited.

## Not validated
No new Yahoo historical-data download, real-data backtest, market liquidity/impact model, point-in-time universe, out-of-sample test, or Sharpe/IR certification.
