# V2.2 — 持仓权重漂移、成交金额与费用核算

**ACCOUNTING RESEARCH MODEL / 独立版本 / 不覆盖 V1 或 V2.1**

本版基于 `fix/v2.1-timing` 的提交 `abd4242fe2a71d17a23fe3166b366853709e145e`。
只新增 `v2_2/` 与根目录入口说明；保留已有 `v1/`、`v2_1/` 和 main。
代码只读复用相邻 `v2_1/backtest_v2_1.py` 的因子、预处理、日历、数据接口；不要单独移动 v2_2 而遗漏 v2_1。

## 1. 已实现与未实现

保留 V2.1 的四个因子、横截面预处理、月末信号、下一交易日收盘执行及五分层规则。
本版新增固定持仓单位、自然权重漂移、按成交金额计费、资金守恒求解、逐日与逐资产交易记录。
首次建仓只收费于买入；换仓收费于实际买入与卖出。相同名单恢复等权仍可能产生交易。
不再把手续费平摊到持仓日，也不再用名单替换数量代替金额换手。

**这不是实盘净收益认证。** 默认 10 bps 是每笔买/卖金额的假设比例成本，并非校准过的真实全费用。
忽略手数、整数股、成交量约束、冲击、滑点分解、结算、税费差异和融券；现金利息为零。
允许碎股/连续持仓单位，默认最后一天不强制清仓。
收盘价成交且恰好达到目标权重是理想化假设，不能当作可保证的收盘订单执行。
若输入复权价，持仓单位是**复权价格下的合成单位**，不是券商账户的真实股数；不得另加分红现金而重复计入。
固定股票池、复权数据的时点可得性、样本外验证仍未解决。Sharpe/IR 留到 V2.3。

## 2. 时间顺序

T 月末收盘后产生信号；T+1 交易日收盘执行；T+2 首次计入新仓位的价格收益。
成交日先按当日收盘价计算旧持仓损益，再换仓、扣费。
**成交日可以出现负的净收益，因为手续费当天扣除；这不是提前计入新仓位价格收益。**
继承的 `first_return_date` 指新仓位首次获得收盘到收盘**价格收益**的日期。

没有新订单的日子，持仓单位不变，权重随价格漂移。缺失有效信号时继续持有，不重新等权。
缺少持仓或待买入资产价格直接报错，不填价、不事后换股。

## 3. 自筹资金的计算约定

设成交前各股票市值为 h_i、现金为 c，V = sum(h_i) + c。
目标股票权重 w_i 相对于**扣费后的净值**定义，非负且合计不超过 1。
k = cost_bps / 10000。

```
x + k * sum_i |w_i * x - h_i| = V
成交金额 u_i = w_i * x - h_i
费用 C = k * sum_i |u_i|
扣费后总资产 x = V - C
成交后现金 = c - sum_i u_i - C
```

在 0 <= k < 1、无杠杆多头条件下，左边对 x 严格递增。
程序在 [0, V] 上二分求解，不借钱支付费用。
双精度运算只容忍机器舍入残差；每日验证 `成交前资产 - 成交后资产 - 费用`。

例：现金 1000、全部买入、10 bps，实际买入额为 `1000 / 1.001 = 999.000999...`，费用 `0.999001...`。
不是买足 1000 后再让现金变成 -1，更不是首次建仓收费 2。
例：已有市值 [600,400]，恢复 [50%,50%]，费率10 bps：卖出100.1、买入99.9、费用0.2，最终各499.9。

## 4. 换手与收益字段

`buy_notional` 与 `sell_notional` 均为非负金额；卖出量另用有符号成交额表达。
`traded_fraction = (buy_notional + sell_notional) / equity_before_trade`。
`half_traded_fraction = traded_fraction / 2` 只是明确报告的半总成交比例；首次现金建仓不是双向换仓，不据此乘二重复收费。
`fees = k * (buy_notional + sell_notional)`。

`gross_return_on_net_holdings = equity_before_trade / equity_previous - 1`，是当日实际含历史费用的账户持仓在本次扣费前的收益。
`net_return = equity_after_trade / equity_previous - 1`。
两者差为 `fees / equity_previous`；不是 `fees / equity_before_trade`。

另独立运行同样信号、费率为零的完整持仓账户，写入 `zero_cost_reference/`。
它不是把净收益简单加回费用；其资金路径会不同。
最终零费率净值与含费用净值之差一般不等于累计现金手续费，因为还存在复利影响。

## 5. Mac 运行

从 GitHub 克隆新分支到**新文件夹**，不会使用你之前的 QR_V21_separate：

```bash
cd "$HOME/Downloads" && \
git clone --branch fix/v2.2-accounting --single-branch https://github.com/ace-wenda-li/multi-factor-backtest.git QR_V22_separate && \
cd QR_V22_separate/v2_2 && \
uv venv --python 3.11 .venv && \
uv pip install --python .venv/bin/python -r requirements-v2_2.txt && \
.venv/bin/python -m pytest -q tests ../v2_1/tests && \
.venv/bin/python backtest_v2_2.py --demo --output outputs_v2_2_demo
```

打开结果文件夹（这是一条命令，不是直接输入文件夹路径）：

```bash
open "$HOME/Downloads/QR_V22_separate/v2_2/outputs_v2_2_demo"
```

测试含 V2.1 原有 31 项和 V2.2 新增 43 项，共74项。
当前验证环境是 Linux / Python 3.13.5，尚未在你的 Mac / Python 3.11 上运行 V2.2。
所有离线依赖与之前 V2.1 相同。输出路径只允许全新路径；重复运行请换 `--output` 名称，不要删除旧结果。
人工演示使用与 V2.1 相同的随机种子和12只合成股票 S00–S11，不是真实行情。

复用你已有 V2.1 的人工输入，无需下载：

```bash
.venv/bin/python backtest_v2_2.py \
  --csv-dir "$HOME/Downloads/QR_V21_separate/v2_1/outputs_demo" \
  --output outputs_v2_2_from_v21
```

CSV 输入需有 date 首列及一致股票列的 `close.csv`、`volume.csv`。
完整历史的复权价不能自动证明时点可得性，缺失数据不能事后选择性剔除。
可选 `--download` 沿用 V2.1 的 Yahoo 接口，需要另外安装 yfinance；本轮未执行或验证联网下载。
`--end` 仍为不含当天的结束日期，默认与 V2.1 相同，避免把更换样本区间混入会计修复。

## 6. 先看哪些输出

- `daily.csv`：每日资产、现金、损益、费用、买卖金额、换手比例和守恒残差。
- `trades.csv`：逐股票成交、持仓单位变化、费用和交易前后权重。
- `weights_before_trade.csv` / `weights_after_close.csv`：检查权重漂移及再平衡。
- `comparison.csv`：含假设费用与零费率的两条独立账户路径。

另外保留 `targets.csv`、`units_after_close.csv`、`decisions.csv`、`schedule.csv`、输入快照、因子、运行元数据及 SHA256。
`quintiles/Q1` 至 `Q5` 使用同一会计引擎，各自有完整账户记录。
`decisions.csv` 的 `target_scheduled` 表示按信号排定了目标；是否实际成交看 daily/trades，已经处于目标时无需多余交易。

## 7. 验证记录与后续

`validation/` 包含实际运行的测试输出、人工演示日志及60个 CSV 重跑比较记录。
已有输出路径拒绝覆盖也已验证；无真实市场收益数字用于简历。
下一步先在 Mac 验收，然后再做真实数据质量检查与 V2.3 的指标核算。
