import numpy as np
import pandas as pd
import pytest
from factor_validation_v2_3 import (rank_corr, monthly_ic, ic_summary, metrics,
                                    performance, factor_correlation, analyze,
                                    demo_data, compute_factors, preprocess_factors)


def test_spearman_reversed():
    r,n=rank_corr(pd.Series([1.,2.,3.,4.]),pd.Series([4.,3.,2.,1.]))
    assert n==4 and r==pytest.approx(-1)


def test_tied_and_missing():
    r,n=rank_corr(pd.Series([1.,1.,2.,np.nan]),pd.Series([2.,2.,3.,4.]))
    assert n==3 and r==pytest.approx(1)


def test_constant_ic_is_nan():
    r,n=rank_corr(pd.Series([1.,1.,1.]),pd.Series([1.,2.,3.]))
    assert np.isnan(r)


def test_ic_uses_post_execution_price_and_never_entry_jump():
    c,v=demo_data()
    date=pd.Timestamp('2024-02-01')
    j=c.index.get_loc(date)
    c.loc[date,:]=100.
    c.iloc[j+2,:]=100.+np.arange(c.shape[1])
    score=pd.DataFrame(np.tile(np.arange(c.shape[1]),(len(c),1)),index=c.index,columns=c.columns)
    ic=monthly_ic({'momentum':score},c,horizon=2)
    jan=ic[(ic.factor=='momentum_20d') & (ic.signal_date==pd.Timestamp('2024-01-31'))].iloc[0]
    assert jan.execution_date==date and jan.outcome_date==c.index[j+2]
    assert jan.rank_ic==pytest.approx(1)


def test_tail_dropped_not_zero_ic():
    c,v=demo_data()
    f=pd.DataFrame(1.,index=c.index,columns=c.columns)
    assert monthly_ic({'momentum':f},c,horizon=500).empty


def test_ic_period_labels_must_mature_inside_period():
    d=pd.DataFrame({'factor':['f','f'],'signal_date':pd.to_datetime(['2021-12-31','2022-02-01']),
                    'outcome_date':pd.to_datetime(['2022-01-30','2022-02-28']),
                    'rank_ic':[.4,.2]})
    s=ic_summary(d)
    assert s.query("period=='train'").iloc[0].n_signals==0
    assert s.query("period=='validation'").iloc[0].n_signals==1


def test_cagr_not_sharpe_numerator():
    x=pd.Series([.1,-.05,.07,-.02],index=pd.bdate_range('2024-01-01',periods=4))
    m=metrics(x)
    assert m['sharpe_rf_zero']==pytest.approx(x.mean()*np.sqrt(252)/x.std(ddof=1))


def test_initial_nav_in_drawdown():
    x=pd.Series([-.1,.1],index=pd.bdate_range('2024-01-01',periods=2))
    assert metrics(x)['max_drawdown']==pytest.approx(-.1)


def test_ir_zero_tracking_error_is_nan():
    x=pd.Series([.1,.0,-.03],index=pd.bdate_range('2024-01-01',periods=3))
    p=performance({'a':x,'universe_equal_weight':x})
    assert np.isnan(p.query("strategy=='a' and period=='full'").iloc[0].information_ratio)


def test_return_index_mismatch_rejected():
    a=pd.Series([.1],index=[pd.Timestamp('2024-01-01')])
    b=pd.Series([.1],index=[pd.Timestamp('2024-01-02')])
    with pytest.raises(ValueError,match='misaligned'):
        performance({'a':a,'universe_equal_weight':b})


def test_demo_has_four_factors_plus_composite_and_baseline():
    c,v=demo_data()
    r=analyze(c,v)
    assert len(r['accounts'])==6
    assert len(r['performance'].query("period=='full'"))==6
    assert r['performance'].benchmark.eq('universe_equal_weight').all()


def test_cross_sectional_corr_has_six_pairs_per_month():
    c,v=demo_data()
    p=preprocess_factors(compute_factors(c,v))
    cor=factor_correlation(p,c)
    assert len(cor)==6*4
    assert cor.factor_a.ne(cor.factor_b).all()
