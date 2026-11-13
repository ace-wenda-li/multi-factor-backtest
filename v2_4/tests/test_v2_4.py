"""Offline audit tests; no investment claims and no live network requests."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from factor_audit_v2_4 import (Data, verify_engines, validate, read_data, volume_score,
    score_account, static_controls, attribution, ic_records, perf, concentration,
    split_audit, run_audit, save_run, compare_previous, demo_data, download)
from backtest_v2_1 import compute_factors, preprocess_factors
from backtest_v2_2 import backtest, simulate_account


@pytest.fixture
def data():
    c,v = demo_data()
    return Data(c,v,c.copy(),v*0.)


@pytest.fixture(scope="module")
def result():
    c,v = demo_data()
    d=Data(c,v,c.copy(),v*0.)
    return d, run_audit(d)


def test_source_engines_match_known_github_blobs():
    verify_engines()


def test_volume_score_identical_to_v21(data):
    old=preprocess_factors(compute_factors(data.close,data.volume))["turnover"]
    assert_frame_equal(old,volume_score(data.volume))


def test_dynamic_account_identical_to_v22(data):
    score=volume_score(data.volume)
    old=backtest(data.close,score)
    new=score_account(data.close,score)
    assert_frame_equal(old.daily,new.daily)
    assert_frame_equal(old.decisions,new.decisions)


def test_three_controls_share_entry_date_and_frozen_list(result):
    d,r=result
    entry=pd.Timestamp(r['frozen']['execution_date'])
    expected=set(r['frozen']['names'])
    for name in ('dynamic_volume','static_monthly','static_buy_hold'):
        a=r['accounts'][name]
        assert a.trades.date.min()==entry
        assert set(a.trades[a.trades.date==entry].ticker)==expected
    assert r['frozen']['signal_date'].startswith('2024-01-31')


def test_static_hold_trades_only_initially(result):
    _,r=result
    a=r['accounts']['static_buy_hold']
    assert a.trades.date.nunique()==1
    assert a.trades.side.eq('BUY').all()
    active=a.units_after_close.loc[a.trades.date.min():]
    assert np.allclose(active,active.iloc[0])


def test_static_monthly_never_adds_new_names(result):
    _,r=result
    a=r['accounts']['static_monthly']
    assert set(a.trades.ticker)==set(r['frozen']['names'])
    assert a.trades.date.nunique()==4


def test_first_execution_has_fee_no_preentry_price_gain(result):
    _,r=result
    a=r['accounts']['dynamic_volume']
    day=a.daily.loc[pd.Timestamp(r['frozen']['execution_date'])]
    assert day.market_pnl==0
    assert day.net_return==pytest.approx(1/1.001-1)


def test_attribution_reconciles_daily_and_total(result):
    d,r=result
    a=r['accounts']['dynamic_volume']
    total,daily,res=attribution(d.close,a)
    assert total.net_pnl.sum()==pytest.approx(a.daily.equity_after_trade.iloc[-1]-1e6)
    assert total.contribution_to_total_return.sum()==pytest.approx(a.daily.equity_after_trade.iloc[-1]/1e6-1)
    assert np.allclose(daily.groupby(level='date').daily_return_contribution.sum(),a.daily.net_return)
    assert np.allclose(daily.groupby(level='date').fees.sum(),a.daily.fees)
    assert res<1e-6


def test_attribution_uses_prior_units_on_switch(data):
    c=data.close.iloc[:25,:2].copy()*0+100.
    orders=c*np.nan
    orders.iloc[1]=[1.,0.]
    orders.iloc[3]=[0.,1.]
    c.iloc[3:,0]=110.
    c.iloc[3,1]=200.
    c.iloc[4:,1]=220.
    a=simulate_account(c,orders,initial_cash=1000.,cost_bps=0)
    total,daily,_=attribution(c,a)
    assert daily.loc[(c.index[3],c.columns[0]),'gross_pnl']==pytest.approx(100.)
    assert daily.loc[(c.index[3],c.columns[1]),'gross_pnl']==0
    assert daily.loc[(c.index[4],c.columns[1]),'gross_pnl']==pytest.approx(110.)
    assert total.net_pnl.sum()==pytest.approx(210.)


def test_cash_only_attribution_is_zero(data):
    c=data.close.iloc[:5]
    a=simulate_account(c,c*np.nan)
    total,detail,_=attribution(c,a)
    assert (total.net_pnl==0).all()


def test_terminal_hold_not_forced_sale(result):
    _,r=result
    a=r['accounts']['dynamic_volume']
    assert a.trades.date.max()<a.daily.index[-1]
    assert a.units_after_close.iloc[-1].sum()>0


def test_future_perturbation_cannot_change_past_or_frozen_list(data):
    cutoff=pd.Timestamp('2024-03-15')
    a=score_account(data.close,volume_score(data.volume))
    controls,freeze=static_controls(data.close,a)
    c,v=data.close.copy(),data.volume.copy()
    c.loc[c.index>cutoff]*=np.linspace(.1,10,c.shape[1])
    v.loc[v.index>cutoff]*=np.linspace(1,100,c.shape[1])
    b=score_account(c,volume_score(v)); controls2,freeze2=static_controls(c,b)
    assert freeze==freeze2
    assert_frame_equal(a.daily.loc[:cutoff],b.daily.loc[:cutoff])
    for name in controls:
        assert_frame_equal(controls[name].daily.loc[:cutoff],controls2[name].daily.loc[:cutoff])


def test_truncated_history_same_earlier_pnl(data):
    cutoff=pd.Timestamp('2024-03-15')
    a=score_account(data.close,volume_score(data.volume))
    b=score_account(data.close.loc[:cutoff],volume_score(data.volume.loc[:cutoff]))
    assert_frame_equal(a.daily.loc[:cutoff],b.daily)


def test_leave_one_out_all_names_and_recomputed_result(result):
    d,r=result
    assert set(r['leave_one_out'].excluded)==set(d.close.columns)
    ticker=d.close.columns[0]
    cc=d.close.drop(columns=ticker); vv=d.volume.drop(columns=ticker)
    a=score_account(cc,volume_score(vv))
    m=r['leave_one_out'].set_index('excluded').loc[ticker]
    assert m.total_return==pytest.approx(a.daily.equity_after_trade.iloc[-1]/1e6-1)


def test_exclusion_not_silently_reduce_number_selected(data):
    with pytest.raises(ValueError,match='n\\+1'):
        run_audit(data,n=data.close.shape[1])
    r=run_audit(data,n=data.close.shape[1],leave_one_out=False)
    assert r['leave_one_out'].empty


def test_proxy_optional_not_adjusted_close_substitution(data):
    r=run_audit(Data(data.close,data.volume),leave_one_out=False)
    assert 'dollar_activity_proxy' not in r['accounts']
    assert r['definitions'].set_index('signal').loc['dollar_activity_proxy','status']=='NOT_RUN'
    assert r['definitions'].set_index('signal').loc['true_float_turnover','status']=='NOT_RUN'


def test_proxy_uses_mean_of_product_not_product_of_means(data):
    d=Data(data.close,data.volume,data.source_close)
    r=run_audit(d,leave_one_out=False)
    score=preprocess_factors({'x':np.log1p((d.source_close*d.volume).rolling(20).mean())})['x']
    expected=score_account(d.close,score)
    assert_frame_equal(expected.daily,r['accounts']['dollar_activity_proxy'].daily)


def test_metrics_use_arithmetic_sharpe_and_initial_nav():
    r=pd.Series([-.1,.02,.07])
    m=perf(r,r)
    assert m['sharpe_rf_zero']==pytest.approx(r.mean()/r.std()*np.sqrt(252))
    assert m['max_drawdown']==pytest.approx(-.1)
    assert np.isnan(m['ir_vs_universe'])


def test_split_table_no_claim_of_adjustment(data):
    data.splits.iloc[25,0]=4.
    s=split_audit(data)
    assert len(s)==1 and s.iloc[0].split_ratio==4
    assert s.iloc[0].date==data.close.index[25]
    assert split_audit(Data(data.close,data.volume)).empty


def test_stock_specific_volume_units_can_change_rank(data):
    v=data.volume*0+10
    v.iloc[:,0]=9
    a=volume_score(v)
    v.iloc[:,0]*=2
    b=volume_score(v)
    assert a.iloc[-1,0]<a.iloc[-1,1]
    assert b.iloc[-1,0]>b.iloc[-1,1]


def test_concentration_is_frequency_not_pnl(result):
    _,r=result
    q=r['concentration']
    assert q.selected_months.sum()==40
    assert q.fraction.between(0,1).all()
    assert 'pnl' not in ''.join(q.columns)


def test_ic_entry_date_and_maturity(data):
    sc=volume_score(data.volume)
    ic=ic_records(sc,data.close)
    first=ic.iloc[0]
    j=data.close.index.get_loc(first.execution_date)
    assert first.outcome_date==data.close.index[j+20]
    assert ic.outcome_date.max()<=data.close.index[-1]


@pytest.mark.parametrize('field',['close','volume','source_close','splits'])
def test_missing_input_rejected_without_dropping_stock(data,field):
    getattr(data,field).iloc[3,0]=np.nan
    with pytest.raises(ValueError,match='missing/nonfinite'):
        validate(data)


def test_missing_exchange_session_rejected(data):
    ix=data.close.index.delete(3)
    with pytest.raises(ValueError,match='Missing sessions'):
        validate(Data(data.close.loc[ix],data.volume.loc[ix]))


def test_misaligned_columns_rejected(data):
    with pytest.raises(ValueError,match='match close'):
        validate(Data(data.close,data.volume.iloc[:,::-1]))


def test_negative_volume_rejected(data):
    data.volume.iloc[0,0]=-1
    with pytest.raises(ValueError,match='invalid price'):
        validate(data)


def test_existing_output_is_never_overwritten(tmp_path,result):
    d,r=result
    out=tmp_path/'out';out.mkdir();marker=out/'old.txt';marker.write_text('KEEP')
    with pytest.raises(FileExistsError):
        save_run(out,d,r,{})
    assert marker.read_text()=='KEEP'


def test_snapshot_csv_roundtrip_and_manifest(tmp_path,result):
    d,r=result
    out=tmp_path/'out'
    save_run(out,d,r,{'source':'TEST'})
    replay=read_data(out/'snapshot')
    rr=run_audit(replay,leave_one_out=False)
    assert_frame_equal(r['accounts']['dynamic_volume'].daily,rr['accounts']['dynamic_volume'].daily,check_exact=False,check_names=False,check_freq=False,rtol=1e-11,atol=1e-8)
    info=json.loads((out/'RUN_INFO.json').read_text())
    assert 'snapshot/close.csv' in info['files_sha256']
    import hashlib
    for name,digest in info['files_sha256'].items():
        assert hashlib.sha256((out/name).read_bytes()).hexdigest()==digest


def test_reference_comparison_flags_changed_returns(tmp_path,result):
    _,r=result
    a=r['accounts']['dynamic_volume']
    old=a.daily.copy();old.iloc[-1,old.columns.get_loc('net_return')]+=.01
    old.to_csv(tmp_path/'daily_log_volume_20d.csv')
    q=compare_previous(tmp_path,a)
    assert q['dates_equal']
    assert q['max_abs_net_return_difference']==pytest.approx(.01)


def test_cli_existing_dir_stops_before_network(tmp_path):
    script=Path(__file__).resolve().parents[1]/'factor_audit_v2_4.py'
    p=subprocess.run([sys.executable,str(script),'--download','--output',str(tmp_path)],capture_output=True,text=True)
    assert p.returncode==2
    assert 'already exists' in p.stderr


def test_download_adapter_with_mock(data,monkeypatch):
    # Tests API extraction/options only, NOT a live Yahoo request.
    from types import SimpleNamespace
    frame=pd.concat({'Adj Close':data.close,'Close':data.close*2,'Volume':data.volume,'Stock Splits':data.splits},axis=1)
    calls=[]
    def fake(*args,**kwargs):
        calls.append(kwargs)
        # Reindex real default ticker names for this small mocked panel.
        return frame
    import factor_audit_v2_4 as mod
    monkeypatch.setattr(mod,'TICKERS',list(data.close.columns))
    monkeypatch.setitem(sys.modules,'yfinance',SimpleNamespace(download=fake))
    actual=download('2024-01-01','2024-05-16')
    assert_frame_equal(actual.close,data.close,check_freq=False)
    assert_frame_equal(actual.source_close,data.close*2,check_freq=False)
    assert calls[0]['auto_adjust'] is False and calls[0]['actions'] is True


def test_download_adapter_missing_adj_close_rejected(data,monkeypatch):
    from types import SimpleNamespace
    frame=pd.concat({'Close':data.close,'Volume':data.volume},axis=1)
    monkeypatch.setitem(sys.modules,'yfinance',SimpleNamespace(download=lambda *a,**k:frame))
    with pytest.raises(ValueError,match='Adj Close'):
        download('2024-01-01','2024-05-16')


def test_run_does_not_mutate_input_frames(data):
    before=[getattr(data,k).copy(deep=True) for k in ("close","volume","source_close","splits")]
    run_audit(data,leave_one_out=False)
    for k,f in zip(("close","volume","source_close","splits"),before):
        assert_frame_equal(getattr(data,k),f)
