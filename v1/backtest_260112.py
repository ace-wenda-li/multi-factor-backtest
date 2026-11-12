import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
from scipy import stats
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
def backtest(close, composite_factor, n_stocks=10, rebalance_freq="ME", cost_bps=10):
    """
    cost_bps: 单边交易成本（万分之几），默认10 bps，双边就是20 bps (0.2%)
    """
    rebalance_dates = close.resample(rebalance_freq).last().index
    rebalance_dates = [d for d in rebalance_dates if d in close.index]

    portfolio_returns, positions = [], []
    prev_selected = set()
    turnovers = []
    
    for i, date in enumerate(rebalance_dates[:-1]):
        next_date = rebalance_dates[i+1]
        if date not in composite_factor.index:
            continue
        factor_values = composite_factor.loc[date].dropna()
        if len(factor_values) < n_stocks:
            continue
            
        selected = factor_values.nlargest(n_stocks).index.tolist()
        positions.append((date, selected))
        
        # --- 计算换手率 ---
        current_selected = set(selected)
        # 换手率 = 新买入的股票数量 / 总股票数
        turnover = len(current_selected - prev_selected) / n_stocks
        turnovers.append(turnover)
        prev_selected = current_selected
        
        # 计算该持仓期的日收益
        period_returns = close.loc[date:next_date, selected].pct_change().iloc[1:]
        daily_port_ret = period_returns.mean(axis=1)
        
        # --- 扣除交易成本 ---
        # 双边成本 = 换手率 * 2 * 单边手续费
        # 将这笔一次性成本平摊到持仓期内的每一天
        if len(daily_port_ret) > 0:
            total_cost = turnover * 2 * (cost_bps / 10000.0)
            daily_cost = total_cost / len(daily_port_ret)
            daily_port_ret = daily_port_ret - daily_cost
            
        portfolio_returns.append(daily_port_ret)

    if not portfolio_returns:
        raise ValueError("未生成任何组合收益，请检查数据日期与因子值。")
        
    port_ret = pd.concat(portfolio_returns).sort_index()
    port_ret = port_ret[~port_ret.index.duplicated(keep='first')]
    
    avg_turnover = np.mean(turnovers)
    return port_ret, positions, avg_turnover 
    # 加入 cost_bps=10 (即单边千分之一)


# ==================== IC计算 ====================

def compute_ic_analysis(composite_factor, close, forward_days=20):
    """
    计算 Rank IC (Spearman 秩相关)
    forward_days: 预测未来多少天的收益，默认 20天（约一个月）
    """
    # 计算未来收益并前移对齐（shift(-forward_days) 是为了让当天的因子对应未来的收益）
    forward_ret = close.pct_change(forward_days).shift(-forward_days)
    
    ic_records = []
    for date in composite_factor.index:
        if date not in forward_ret.index:
            continue
            
        f = composite_factor.loc[date].dropna()
        r = forward_ret.loc[date].dropna()
        common_stocks = f.index.intersection(r.index)
        
        # 如果有效股票数量太少，跳过该截面
        if len(common_stocks) < 10:
            continue
            
        # 计算秩相关系数 (Rank IC)
        ic, _ = stats.spearmanr(f[common_stocks], r[common_stocks])
        if not np.isnan(ic):
            ic_records.append({"date": date, "rank_ic": ic})
            
    ic_df = pd.DataFrame(ic_records).set_index("date")
    
    # 计算 IC 指标
    mean_ic = ic_df["rank_ic"].mean()
    ic_std = ic_df["rank_ic"].std()
    icir = mean_ic / ic_std if ic_std != 0 else np.nan
    ic_win_rate = (ic_df["rank_ic"] > 0).mean()
    
    return ic_df, {
        "Mean IC": mean_ic, 
        "IC Std": ic_std, 
        "ICIR": icir, 
        "IC Win Rate": ic_win_rate
    }    
    
# ==================== 分层回测 ====================

def layered_backtest(close, composite_factor, n_groups=5, rebalance_freq="ME"):
    rebalance_dates = close.resample(rebalance_freq).last().index
    rebalance_dates = [d for d in rebalance_dates if d in close.index]

    group_returns = {f"Q{i+1}": [] for i in range(n_groups)}

    for i, date in enumerate(rebalance_dates[:-1]):
        next_date = rebalance_dates[i+1]
        if date not in composite_factor.index:
            continue
        f = composite_factor.loc[date].dropna()
        if len(f) < n_groups * 2:
            continue

        # 用 qcut 等分，labels 从低到高
        try:
            groups = pd.qcut(f, n_groups, labels=[f"Q{i+1}" for i in range(n_groups)], duplicates='drop')
        except ValueError:
            continue
            
        period_ret = close.loc[date:next_date].pct_change().iloc[1:]

        for g in groups.unique():
            stocks = groups[groups == g].index
            stocks = [s for s in stocks if s in period_ret.columns]
            if stocks and len(stocks) > 0:
                group_returns[g].append(period_ret[stocks].mean(axis=1))

    cum_groups = {}
    for g, rets in group_returns.items():
        if rets:
            daily = pd.concat(rets).sort_index()
            cum_groups[g] = (1 + daily).cumprod().iloc[-1] - 1
    return cum_groups

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
    session = curl_requests.Session(impersonate="chrome")
    
    # 1. 下载股票数据
    close, volume = download_data(TICKERS, START_DATE, END_DATE)
    print(f"Data shape: {close.shape}")

    # 2. 因子与回测
    factor_dict = compute_factors(close, volume, lookback=LOOKBACK)
    processed = preprocess_factors(factor_dict)
    composite = combine_factors(processed)
    
    print("Running backtest...")
    port_ret, positions, avg_turnover = backtest(close, composite, n_stocks=N_STOCKS, rebalance_freq=REBALANCE_FREQ, cost_bps=10)    
    
    # ==================== Step 1: 加入 SPY 基准 ====================
    print("Downloading SPY benchmark...")
    # 【修复点】：加入 .squeeze() 将其强制转为一维 Series
    spy_data = yf.download("SPY", start=START_DATE, end=END_DATE, auto_adjust=True, progress=False, session=session)["Close"].squeeze()
    spy_ret = spy_data.pct_change().dropna()
    
    # 对齐日期：确保策略和基准在同一天比较
    spy_ret = spy_ret.reindex(port_ret.index).ffill().dropna()
    port_ret_aligned = port_ret.loc[spy_ret.index]  # 确保策略也使用对齐后的日期

    # 计算策略与基准的绩效
    metrics_strategy = performance_metrics(port_ret_aligned)
    metrics_spy = performance_metrics(spy_ret)
    
    # 计算超额收益（Excess Return）与信息比率（Information Ratio）
    excess_ret = port_ret_aligned - spy_ret
    ann_excess = excess_ret.mean() * 252
    tracking_error = excess_ret.std() * np.sqrt(252)
    info_ratio = ann_excess / tracking_error if tracking_error != 0 else np.nan

    print("\n--- Performance Metrics ---")
    print(f"{'Metric':<25} | {'Strategy':<10} | {'SPY':<10}")
    print("-" * 50)
    print(f"{'Total Return':<25} | {metrics_strategy['Total Return']:<10.4f} | {metrics_spy['Total Return']:<10.4f}")
    print(f"{'Annualized Return':<25} | {metrics_strategy['Annualized Return']:<10.4f} | {metrics_spy['Annualized Return']:<10.4f}")
    print(f"{'Annualized Volatility':<25} | {metrics_strategy['Annualized Volatility']:<10.4f} | {metrics_spy['Annualized Volatility']:<10.4f}")
    print(f"{'Sharpe Ratio':<25} | {metrics_strategy['Sharpe Ratio']:<10.4f} | {metrics_spy['Sharpe Ratio']:<10.4f}")
    print(f"{'Max Drawdown':<25} | {metrics_strategy['Max Drawdown']:<10.4f} | {metrics_spy['Max Drawdown']:<10.4f}")
    print("-" * 50)
    print(f"Annualized Excess Return: {ann_excess:.4f}")
    print(f"Information Ratio (IR):   {info_ratio:.4f}")
    print(f"Average Monthly Turnover:  {avg_turnover*100:.2f}%")
    print(f"Estimated Annual Cost:     {avg_turnover * 12 * 2 * 10 / 100:.2f}%") # 估算年化成本

    # 3. 绘图对比
    cum_ret = (1 + port_ret_aligned).cumprod()
    cum_spy = (1 + spy_ret).cumprod()
    
    plt.figure(figsize=(12, 6))
    plt.plot(cum_ret.index, cum_ret.values, label="Multi-Factor Strategy", linewidth=2)
    plt.plot(cum_spy.index, cum_spy.values, label="SPY Benchmark", linestyle="--", linewidth=2, color="gray")
    
    plt.title("Cumulative Return: Strategy vs. SPY")
    plt.xlabel("Date")
    plt.ylabel("Cumulative Return")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig("cumulative_return_vs_spy.png", dpi=150) # 保存为新文件名
    plt.show()


        # ==================== Step 2: 因子 IC 分析 ====================
    print("\nComputing Rank IC...")
    ic_df, ic_metrics = compute_ic_analysis(composite, close, forward_days=20)
    
    print("\n--- Factor IC Analysis (20-Day Forward) ---")
    for k, v in ic_metrics.items():
        print(f"{k}: {v:.4f}")

    # 画 IC 柱状图
    plt.figure(figsize=(12, 4))
    # 正IC画蓝色，负IC画红色
    colors = ['tab:blue' if x > 0 else 'tab:red' for x in ic_df['rank_ic']]
    plt.bar(ic_df.index, ic_df['rank_ic'], color=colors, width=2.0, alpha=0.7)
    
    # 加上 60 天滑动平均线，看 IC 趋势
    ic_ma = ic_df['rank_ic'].rolling(3, min_periods=1).mean()
    plt.plot(ic_df.index, ic_ma, color='black', linewidth=1.5, label='3-Month Moving Average')
    
    plt.axhline(0, color='gray', linestyle='--', linewidth=1)
    plt.title("Rank IC Series (20-Day Forward Return)")
    plt.xlabel("Date")
    plt.ylabel("Rank IC")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig("ic_series.png", dpi=150)
    plt.show()


        # ==================== Step 3: 分层回测 ====================
    print("\nRunning Layered Backtest (Quintiles)...")
    layered_rets = layered_backtest(close, composite, n_groups=5, rebalance_freq=REBALANCE_FREQ)
    
    print("\n--- Layered Cumulative Returns ---")
    for g, ret in layered_rets.items():
        print(f"{g}: {ret:.4f}")

    # 画分层柱状图
    plt.figure(figsize=(8, 5))
    groups_list = list(layered_rets.keys())
    rets_list = list(layered_rets.values())
    colors = ['#d62728' if r < 0 else '#1f77b4' for r in rets_list]
    
    plt.bar(groups_list, rets_list, color=colors, alpha=0.8)
    plt.title("Layered Backtest Cumulative Return (Q1 to Q5)")
    plt.xlabel("Factor Quintile (Q1=Lowest, Q5=Highest)")
    plt.ylabel("Cumulative Return")
    plt.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    plt.savefig("layered_returns.png", dpi=150)
    plt.show()

    
if __name__ == "__main__":
    main()
