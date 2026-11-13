"""V2.3 -- retrospective factor validation, NEVER a live-trading claim.

Read-only reuse of V2.1 factors and V2.2 accounting. Run from v2_3/.
"""
from pathlib import Path
import argparse
import json
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for folder in ("v2_1", "v2_2"):
    sys.path.insert(0, str(ROOT / folder))
from backtest_v2_1 import (TICKERS, compute_factors, preprocess_factors,
                           combine_factors, monthly_schedule, demo_data, download_data)
from backtest_v2_2 import backtest

SPLITS = {"train": (None, "2021-12-31"),
          "validation": ("2022-01-01", "2022-12-31"),
          "test": ("2023-01-01", "2024-12-31")}
NAMES = {"momentum": "momentum_20d", "volatility": "neg_volatility_20d",
         "turnover": "log_volume_20d", "reversal": "reversal_5d"}


def rank_corr(x, y, minimum=3):
    """Spearman rank IC with pairwise valid observations and average ties."""
    xy = pd.concat([x.rename("x"), y.rename("y")], axis=1)
    xy = xy.replace([np.inf, -np.inf], np.nan).dropna()
    n = len(xy)
    if n < minimum or xy.x.nunique() < 2 or xy.y.nunique() < 2:
        return float("nan"), n
    return float(xy.x.rank().corr(xy.y.rank())), n


def monthly_ic(processed, close, horizon=20, minimum=10):
    """Signal at T close, execute T+1 close, label T+1 to T+1+h close."""
    if horizon < 1 or minimum < 3:
        raise ValueError("horizon >= 1 and minimum >= 3 required")
    signals = {NAMES.get(k, k): v for k, v in processed.items()}
    signals["composite_equal_weight"] = combine_factors(processed)
    for f in signals.values():
        if not f.index.equals(close.index) or not f.columns.equals(close.columns):
            raise ValueError("Factor axes do not match prices")
    rows = []
    for item in monthly_schedule(close.index).itertuples(index=False):
        j = close.index.get_loc(item.execution_date)
        if j + horizon >= len(close):
            continue
        outcome = close.index[j + horizon]
        p0, p1 = close.iloc[j], close.iloc[j+horizon]
        valid = np.isfinite(p0) & np.isfinite(p1) & p0.gt(0) & p1.gt(0)
        future = (p1 / p0 - 1).where(valid)
        for name, frame in signals.items():
            rho, n = rank_corr(frame.loc[item.signal_date], future, minimum)
            rows.append(dict(factor=name, signal_date=item.signal_date,
                             execution_date=item.execution_date, outcome_date=outcome,
                             rank_ic=rho, n_assets=n))
    return pd.DataFrame(rows, columns=["factor","signal_date","execution_date",
                                        "outcome_date","rank_ic","n_assets"])


def ic_summary(ic):
    """Descriptive, NON-annualized ICIR; no independent-sample p-values."""
    rows=[]
    if ic.empty:
        return pd.DataFrame(columns=["factor","period","n_signals","mean_ic","icir","positive_fraction"])
    for name, data in ic.groupby("factor"):
        for period,(start,end) in {"full":(None,None), **SPLITS}.items():
            group=data
            if start: group=group[(group.signal_date >= pd.Timestamp(start)) &
                                   (group.outcome_date >= pd.Timestamp(start))]
            if end: group=group[(group.signal_date <= pd.Timestamp(end)) &
                                 (group.outcome_date <= pd.Timestamp(end))]
            x=group.rank_ic.dropna()
            sd=x.std(ddof=1) if len(x)>1 else np.nan
            rows.append(dict(factor=name,period=period,n_signals=len(x),
                             mean_ic=x.mean() if len(x) else np.nan,
                             icir=x.mean()/sd if sd>0 else np.nan,
                             positive_fraction=(x>0).mean() if len(x) else np.nan))
    return pd.DataFrame(rows)


def factor_correlation(processed,close,minimum=10):
    """Monthly contemporaneous Spearman correlations, NOT predictive IC."""
    names=list(processed)
    rows=[]
    for item in monthly_schedule(close.index).itertuples(index=False):
        for j,a in enumerate(names):
            for b in names[j+1:]:
                rho,n=rank_corr(processed[a].loc[item.signal_date],
                                processed[b].loc[item.signal_date],minimum)
                rows.append(dict(signal_date=item.signal_date,factor_a=NAMES.get(a,a),
                                 factor_b=NAMES.get(b,b),spearman=rho,n_assets=n))
    return pd.DataFrame(rows)


def metrics(r):
    r=r.astype(float)
    if r.index.has_duplicates or r.isna().any() or not np.isfinite(r).all() or (r<=-1).any():
        raise ValueError("Nonfinite, duplicate, or invalid returns")
    n=len(r)
    if not n:
        return dict(n_days=0,cagr=np.nan,ann_vol=np.nan,sharpe_rf_zero=np.nan,max_drawdown=np.nan)
    equity=(1+r).cumprod()
    nav=pd.concat([pd.Series([1.0]),equity.reset_index(drop=True)],ignore_index=True)
    vol=r.std(ddof=1)*np.sqrt(252) if n>1 else np.nan
    return dict(n_days=n,cagr=equity.iloc[-1]**(252/n)-1,
                ann_vol=vol,sharpe_rf_zero=(r.mean()*252/vol if vol>0 else np.nan),
                max_drawdown=(nav/nav.cummax()-1).min())


def performance(returns, benchmark="universe_equal_weight"):
    if benchmark not in returns: raise ValueError("Missing benchmark")
    index=returns[benchmark].index
    if any(not r.index.equals(index) for r in returns.values()):
        raise ValueError("Return dates are misaligned")
    rows=[]
    for name,r in returns.items():
        for period,(start,end) in {"full":(None,None),**SPLITS}.items():
            mask=pd.Series(True,index=index)
            if start: mask &= index>=pd.Timestamp(start)
            if end: mask &= index<=pd.Timestamp(end)
            a=r.loc[mask]; b=returns[benchmark].loc[mask]
            m=metrics(a)
            active=a-b
            te=active.std(ddof=1)*np.sqrt(252) if len(active)>1 else np.nan
            annual=active.mean()*252 if len(active) else np.nan
            rows.append(dict(strategy=name,period=period,**m,benchmark=benchmark,
                             active_annual_arithmetic=annual,tracking_error=te,
                             information_ratio=annual/te if te>0 else np.nan))
    return pd.DataFrame(rows)


def analyze(close,volume,cost_bps=10.0,n_stocks=10,horizon=20):
    factors=preprocess_factors(compute_factors(close,volume))
    scores={"composite_equal_weight":combine_factors(factors)}
    scores.update({NAMES.get(k,k):v for k,v in factors.items()})
    # Benchmark selects every stock each month, not SPY.
    scores["universe_equal_weight"]=pd.DataFrame(0.0,index=close.index,columns=close.columns)
    accounts={}
    for name,score in scores.items():
        n=close.shape[1] if name=="universe_equal_weight" else n_stocks
        accounts[name]=backtest(close,score,n_stocks=n,cost_bps=cost_bps)
    return dict(accounts=accounts, ic=monthly_ic(factors,close,horizon),
                correlation=factor_correlation(factors,close),
                ic_summary=ic_summary(monthly_ic(factors,close,horizon)),
                performance=performance({k:r.daily.net_return for k,r in accounts.items()}))


def main():
    p=argparse.ArgumentParser()
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--demo",action="store_true")
    mode.add_argument("--csv-dir",type=Path)
    mode.add_argument("--download",action="store_true")
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--start",default="2018-01-01")
    p.add_argument("--end",default="2024-12-31",help="exclusive")
    p.add_argument("--n-stocks",type=int,default=10)
    p.add_argument("--horizon",type=int,default=20)
    p.add_argument("--cost-bps",type=float,default=10)
    args=p.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        p.error("Output already has files; use a NEW path, never overwrite")
    if args.demo:
        close,volume=demo_data()
        label="SYNTHETIC DEMO -- NOT MARKET EVIDENCE"
    elif args.csv_dir:
        close=pd.read_csv(args.csv_dir/"close.csv",index_col=0,parse_dates=True)
        volume=pd.read_csv(args.csv_dir/"volume.csv",index_col=0,parse_dates=True)
        label="USER-CSV -- PROVENANCE UNVERIFIED"
    else:
        close,volume=download_data(TICKERS,args.start,args.end)
        label="YAHOO DATA -- FIXED SURVIVORSHIP-BIASED UNIVERSE"
    out=analyze(close,volume,args.cost_bps,args.n_stocks,args.horizon)
    args.output.mkdir(parents=True,exist_ok=True)
    for name,key in [("rank_ic","ic"),("ic_summary","ic_summary"),
                     ("factor_correlation","correlation"),("performance","performance")]:
        out[key].to_csv(args.output/(name+".csv"),index=False)
    for name,account in out["accounts"].items():
        account.daily.to_csv(args.output/("daily_"+name+".csv"),index_label="date")
        account.decisions.to_csv(args.output/("decisions_"+name+".csv"),index=False)
    (args.output/"RUN_INFO.json").write_text(json.dumps({
        "version":"V2.3", "data_type":label,"splits":SPLITS,
        "cost_bps_each_buy_and_sell":args.cost_bps,
        "benchmark":"fixed-universe monthly equally weighted, NOT SPY",
        "method":"precommitted factor weights; retrospective chronological slices",
        "warning":"No untouched holdout; results are not investment evidence",
    },indent=2,ensure_ascii=False),encoding="utf8")
    print(label)
    print("V2.3 retrospective diagnostics only; no certified out-of-sample alpha")
    print(out["performance"].query("period=='full'")[["strategy","cagr","sharpe_rf_zero","information_ratio"]])
    print("Saved to",args.output.resolve())

if __name__=="__main__":
    main()
