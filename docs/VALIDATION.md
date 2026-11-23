# Validation record

Recorded on 2026-11-23. This record concerns implementation and packaging checks using synthetic data, not validation of historical market performance.

## Regression suite

```text
........................................................................ [ 58%]
...................................................                      [100%]
123 passed in 17.69s
```

The consolidated suite retains tests of signal timing, cross-sectional processing, exchange sessions, account reconciliation, transaction fees, static controls, attribution, leave-one-out analysis, input validation and output-directory protection. A source-integrity case checks that modified engine bytes are rejected; saved-run tests check that actual source fingerprints are recorded.

Command from the repository root:

```bash
python -m pytest -q
```

## Comparison with the source implementation

The deterministic demo was run with the original audit implementation at upstream revision `ae2876c3ae2805bd673b3f09d9fbfa320a51c98b` and with the consolidated package.

- The complete sets of **53 exported CSV files** were byte-identical.
- The frozen initial selection record was byte-identical.
- The maximum absolute daily P&L reconciliation residual was approximately **2.99 × 10⁻¹⁰** account currency units.

This comparison supports preservation of the tested calculations during consolidation. It is not evidence that all possible inputs or market scenarios behave correctly.

## Notebook execution

All **nine code cells** were executed sequentially in one Python process. The published notebook contains the resulting tables and two actual rendered figures. Inputs were synthetic; no market download was made.

Execution used IPython rich-output capture and the Matplotlib Agg renderer. A separate live Jupyter kernel could not start because the validation environment restricted local sockets. The recorded outputs therefore establish successful in-process code-cell execution, not a successful browser/Jupyter-server session. The execution method is also recorded in notebook metadata.

## Environment

| Component | Version |
|---|---|
| Python | 3.12.14 |
| NumPy | 2.3.5 |
| Pandas | 2.2.3 |
| exchange-calendars | 4.13.1 |
| pytest | 9.0.2 |
| Matplotlib | 3.11.2 |
| IPython | 9.19.1 |
| nbformat | 5.11.1 |

Editable installation of the packaged project succeeded in the isolated validation environment. Python 3.11 is the declared minimum; this record does not claim a new Python 3.11 or macOS run.

## Interpretation

No new live market run, untouched holdout assessment, real execution test, or profitability certification was performed for this packaging update. See [Research design](RESEARCH.md) and [Data and reproducibility](DATA.md) for the retained assumptions.
