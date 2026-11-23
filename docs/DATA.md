# Data and reproducibility

## Input modes

| Mode | Purpose | Interpretation |
|---|---|---|
| `demo` | Generate a deterministic synthetic price/volume panel | Offline workflow demonstration; not market evidence |
| `csv` / `--csv-dir` | Read an existing saved input snapshot | Reproducible inputs, subject to a separate provenance review |
| `download` / `--download` | Request a new Yahoo snapshot through the optional adapter | A new vendor snapshot, not guaranteed to reproduce an older download |

The main notebook defaults to `demo`. Market access is an explicit choice; failure does not silently switch modes or replace missing data.

## CSV schema

Input files have a first column of session dates and one numeric column per ticker.

| File | Required | Meaning |
|---|---|---|
| `close.csv` | Yes | Positive prices used for account valuation and returns |
| `volume.csv` | Yes | Nonnegative reported share volume |
| `source_close.csv` | No | Positive provider-basis close for the optional activity proxy |
| `splits.csv` | No | Nonnegative split-event values supplied by the data source |

All supplied tables must have the same date index and ticker order. Dates must be unique, increasing, timezone-naive normalized session labels, and complete for the requested span under the XNYS calendar. The audit rejects missing, nonfinite, or invalid values rather than silently filling them or dropping stocks.

The strict schema makes inconsistencies visible. It does not establish that the universe was investable historically. Selecting stocks because their full history happens to be complete can itself introduce bias.

## Yahoo adapter

Install the optional download dependency in the same environment:

```bash
python -m pip install -e ".[download]"
```

The adapter requests `auto_adjust=False`, corporate actions, and all tickers in the fixed 30-stock universe. It maps:

- `Adj Close` to accounting prices.
- `Volume` to share volume.
- `Close` to `source_close`.
- `Stock Splits` to split-event values.

`Close` is not assumed to be an as-traded, point-in-time raw price. The product `Close × Volume` remains a provider-basis proxy. Using adjusted accounting prices does not justify adding a second dividend cash flow.

Start and end dates are explicit, with an exclusive end date. For example:

```bash
python -m multifactor.audit \
  --download \
  --start 2018-01-01 \
  --end 2025-01-01 \
  --cost-bps 10 \
  --output outputs/market_001
```

The fixed universe has survivorship bias. A successful download or an exact replay does not certify historical universe membership or vendor adjustment conventions. Network adapter tests use controlled responses; live downloads are separate from the offline demonstration.

## Run artifacts

Each saved audit contains:

| Artifact | Content |
|---|---|
| `snapshot/` | Input CSVs used by that run |
| `RUN_INFO.json` | Data source, parameters, environment information, reconciliation result, packaged-source hashes, and output hashes |
| `comparison.csv` | Portfolio performance under the shared audit design |
| `attribution.csv`, `attribution_daily.csv` | Stock-level P&L and return contributions |
| `leave_one_out.csv` | Universe-exclusion reruns, when enabled |
| `frozen_selection.json` | Initial signal date, execution date, and fixed stock list |
| `rank_ic.csv`, `concentration.csv` | Predictive rank diagnostics and selection frequency |
| `definitions.csv`, `unit_stress.csv`, `split_audit.csv` | Data-definition and unit-sensitivity checks |
| `accounts/` | Daily account records, holdings, targets, and trades |

An existing run directory is never overwritten. The notebook creates a fresh directory when saving; the command-line interface requires a new output path.

To replay a saved snapshot:

```bash
python -m multifactor.audit \
  --csv-dir outputs/market_001/snapshot \
  --output outputs/replay_001
```

Keep the source snapshot, recorded parameters, environment, and code provenance together. Comparing one summary statistic is insufficient to establish identical inputs or equivalent account paths.

## Public materials

The published walkthrough uses synthetic inputs.

Generated local run directories are excluded from routine Git tracking. Before sharing a new empirical result, review its source permissions, data provenance, methodology, and accompanying limitations. Historical summary files without their matching input snapshot cannot reconstruct the original market experiment exactly.
