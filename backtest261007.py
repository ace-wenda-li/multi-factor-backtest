import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
from curl_cffi import requests as curl_requests

# ==================== 参数 ====================
START_DATE = "2018-01-01"
END_DATE = "2024-12-31"
TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA", "JPM", "V", "UNH",
    "HD", "PG", "MA", "DIS", "BAC", "XOM", "PFE", "CSCO", "VZ", "ADBE",
    "NFLX", "INTC", "T", "MRK", "PEP", "KO", "WMT", "CVX", "ABT", "TMO"
]
N_STOCKS = 10
REBALANCE_FREQ = "ME"   # 修复：'M' -> 'ME'
LOOKBACK = 20

# ==================== 数据下载 ====================
def download_data(tickers, start, end):
    session = curl_requests.Session(impersonate="chrome")
    data = yf.download(
        tickers, start=start, end=end,
        auto_adjust=True, progress=False,
        session=session
    )
    if data.empty:
        raise ValueError("yfinance 返回空数据，请稍后重试或切换网络。")
    close = data["Close"].ffill().dropna(how="all")
    volume = data["Volume"].ffill().dropna(how="all")
    common_idx = close.index.intersection(volume.index)
    return close.loc[common_idx], volume.loc[common_idx]

# ==================== 因子计算 ====================
def compute_factors(close, volume, lookback=20):
    returns = close.pct_change()
    mom = close.pct_change(lookback)
    vol = -returns.rolling(lookback).std() * np.sqrt(252)
    turnover = np.log(volume.rolling(lookback).mean() + 1)
    rev = -close.pct_change(5)
    return {"momentum": mom, "volatility": vol, "turnover": turnover, "reversal": rev}

def winsorize(df, limits=(-3, 3)):
    return df.clip(lower=df.mean() + limits[0]*df.std(),
                   upper=df.mean() + limits[1]*df.std(), axis=1)

def preprocess_factors(factor_dict):
    processed = {}
    for name, df in factor_dict.items():
        df = df.replace([np.inf, -np.inf], np.nan)
        df = winsorize(df)
        df = (df - df.mean()) / df.std()
        processed[name] = df
    return processed

def combine_factors(processed_factors):
    weights = {k: 1.0/len(processed_factors) for k in processed_factors}
    composite = None
    for name, df in processed_factors.items():
        composite = df * weights[name] if composite is None else composite + df * weights[name]
    return composite

# ==================== 回测 ====================
def backtest(close, composite_factor, n_stocks=10, rebalance_freq="ME"):
    rebalance_dates = close.resample(rebalance_freq).last().index
    rebalance_dates = [d for d in rebalance_dates if d in close.index]

    portfolio_returns, positions = [], []
    for i, date in enumerate(rebalance_dates[:-1]):
        next_date = rebalance_dates[i+1]
        if date not in composite_factor.index:
            continue
        factor_values = composite_factor.loc[date].dropna()
        if len(factor_values) < n_stocks:
            continue
        selected = factor_values.nlargest(n_stocks).index.tolist()
        positions.append((date, selected))
        period_returns = close.loc[date:next_date, selected].pct_change().iloc[1:]
        portfolio_returns.append(period_returns.mean(axis=1))

    if not portfolio_returns:
        raise ValueError("未生成任何组合收益，请检查数据日期与因子值。")
    port_ret = pd.concat(portfolio_returns).sort_index()
    return port_ret[~port_ret.index.duplicated(keep='first')], positions

# ==================== 绩效 ====================
def performance_metrics(returns, freq=252):
    cum = (1 + returns).cumprod()
    total_ret = cum.iloc[-1] - 1
    ann_ret = (1 + total_ret) ** (freq / len(returns)) - 1
    ann_vol = returns.std() * np.sqrt(freq)
    sharpe = ann_ret / ann_vol if ann_vol != 0 else np.nan
    max_dd = (cum / cum.cummax() - 1).min()
    return {"Total Return": total_ret, "Annualized Return": ann_ret,
            "Annualized Volatility": ann_vol, "Sharpe Ratio": sharpe,
            "Max Drawdown": max_dd}

# ==================== 主程序 ====================
def main():
    print("Downloading data...")
    close, volume = download_data(TICKERS, START_DATE, END_DATE)
    print(f"Data shape: {close.shape}")

    factor_dict = compute_factors(close, volume, lookback=LOOKBACK)
    processed = preprocess_factors(factor_dict)
    composite = combine_factors(processed)

    port_ret, positions = backtest(close, composite, n_stocks=N_STOCKS, rebalance_freq=REBALANCE_FREQ)
    metrics = performance_metrics(port_ret)
    for k, v in metrics.items():
        print(f"  {k}: {v:.4f}")

    cum_ret = (1 + port_ret).cumprod()
    plt.figure(figsize=(10, 5))
    plt.plot(cum_ret.index, cum_ret.values, label="Multi-Factor Portfolio")
    plt.title("Cumulative Return of Multi-Factor Strategy")
    plt.grid(True); plt.legend(); plt.tight_layout()
    plt.savefig("cumulative_return.png", dpi=150); plt.show()

if __name__ == "__main__":
    main()