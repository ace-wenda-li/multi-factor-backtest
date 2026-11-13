# V2.4 — 成交量因子稳健性、持仓归因与数据口径审查

**RETROSPECTIVE AUDIT / 独立研究版 / 不覆盖 V1–V2.3 / 不是实盘收益认证**

基于 `fix/v2.3-factor-validation` 提交 `428a1ea425e75d24939310b2f84b701826ee7067`。
新增 `v2_4/` 与入口文档；只读复用相邻 v2_1、v2_2，不修改 main 或任何旧分支。
启动时核对两份旧引擎的 Git blob SHA；请保留完整仓库目录，不要单独移动 v2_4。

## 1. 研究问题与固定设计

我们已经看过旧样本。因此本版是事后诊断，不是独立样本外检验，也不寻找最优策略。
默认股票池、20日成交量信号、前10名、月末评分、下一交易日收盘执行、每笔买卖金额10bps假设费用均不变。

| 对照 | 名单 | 再平衡 | 用途 |
|---|---|---|---|
| dynamic_volume | 每月成交量前10 | 月度等权 | 复现原成交量策略的核算逻辑 |
| static_monthly | 首次有效信号选出的10只，永久冻结 | 月度等权 | 与动态组比较，诊断重新选股的增量 |
| static_buy_hold | 同一首次名单 | 仅首次建仓，之后固定单位 | 与静态月调组比较再平衡影响 |
| universe_equal_weight | 固定股票池全部股票 | 月度等权 | 简单同股票池基准 |
| dollar_activity_proxy | 按另一口径每月选前10 | 月度等权 | 仅当有 source_close 数据时运行 |

三种主对照使用同一次首次信号和同一个入场日，基准也从该日进入。绝不使用2024年名单倒推2018年持仓。
静态名单的冻结时点与成员保存到 `frozen_selection.json`。
账户仍允许连续/碎股单位、现金利息0、无终点强制清仓；复权价格下为合成单位而非券商实际股数。
价差、冲击、容量、停牌/退市处理、整数手数与真实税费没有得到完整模拟。

## 2. 逐股票归因：可以加总的是什么？

对股票 i、交易日 t，使用前一天收盘后的持仓单位 q：

```
股票市场损益 = q[i,t-1] * (P[i,t] - P[i,t-1])
股票净损益 = 股票市场损益 - 该股票当日实际交易费用
当日收益贡献 = 股票净损益 / 昨日账户资产
全期累计收益贡献 = 股票净损益全期合计 / 初始资金
```

日贡献加总等于账户当日净收益；全期累计贡献加总等于账户全期累计收益。
**这不是单只股票CAGR，不把日贡献简单相加当复合收益，不把持仓频率当利润，也不是风险调整后的Alpha归因。**
未实现损益同样按日盯市计入。使用复权价格时不得额外加入分红现金造成重复计算。
校验逐股票损益、费用与资金守恒；测试包含换仓日旧仓收益归属、首次买入费和手算案例。

## 3. 成交量定义与拆股边界

原信号是 `log1p(mean20(Volume))`，不是流通股换手率。
可选信号是 `log1p(mean20(source_close * Volume))`：先逐日相乘再平均，不是两列均值相乘。
Yahoo下载时 `source_close` 来自 `auto_adjust=False` 的 `Close`，**不保证是当时未经任何拆股调整的成交价**。
因此产品明确叫 **provider-basis dollar activity proxy**（供应商口径成交额代理），不是经核实的真实逐笔成交金额。
记账使用同一次响应的 `Adj Close`，避免把股息调整后的价格默认为成交额计价基准。
缺少 `source_close.csv` 时跳过代理实验，不用复权价格偷偷代替。

`split_audit.csv` 只列响应中已给出的拆股事件及前后最多5个交易日的成交量中位数，边界可能不足5日。
它用于检查，不自动反向拆分或再复权，不把量比变化当作拆股影响的因果估计。
`unit_stress.csv` 分别把每只股票整条成交量乘2，记录名单变化次数，用于暴露单位依赖性；**不是拆股修复，也不是新的策略**。
**真实流通股换手率：NOT_RUN。** 没有经核实的历史流通股数量及当时可得时间，禁止用当前流通股数回填历史。

官方口径参考：
- https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html
- https://help.yahoo.com/kb/SLN28256.html
- https://ranaroussi.github.io/yfinance/advanced/price_repair.html
- https://github.com/ranaroussi/yfinance/blob/main/yfinance/utils.py
这些文档不能证明用户已有下载的每个数值正确；`auto_adjust=False` 本身不等于取得点时原始数据。

## 4. 敏感性分析，不事后挑选赢家

默认对股票池所有股票逐一排除，保持选股数不变，重新计算横截面标准化、重新选股并重跑账户。
每个排除实验都另建删掉同一股票的等权基准；报告IR、收益、IC以及相对原动态策略的CAGR变化。
不得把“排除某股的绩效差”当作该股收益贡献，它还改变了其他持仓、费用及复利。
若股票数量不足 n+1，必须明确使用 `--no-leave-one-out`，不偷偷缩小持仓数。
IC继续使用次日成交收盘至之后20交易日的收益，可能跨月重叠，仅描述，无独立样本显著性认证。
全年和逐年绩效均为回顾性报告，无调参、因子择时或新样本外策略。

## 5. 先在 Mac 跑离线演示

```bash
cd "$HOME/Downloads" && \
git clone --branch fix/v2.4-factor-audit --single-branch \
  https://github.com/ace-wenda-li/multi-factor-backtest.git QR_V24_separate && \
cd QR_V24_separate/v2_4 && \
uv venv --python 3.11 .venv && \
uv pip install --python .venv/bin/python -r requirements-v2_4.txt && \
.venv/bin/python -m pytest -q tests ../v2_1/tests && \
.venv/bin/python factor_audit_v2_4.py --demo --output outputs_v24_demo
```

本轮本地实际验证范围为36项新增测试与31项V2.1时序测试（67项），不是宣称已重新执行全部V2.2/V2.3旧测试。
新增测试检查V2.2账户一致性与旧引擎内容哈希。验证机器Linux/Python3.13.5；Mac/Python3.11待本机验收。
旧版全部测试文件仍保留在相应目录，未删除。

```bash
open "$HOME/Downloads/QR_V24_separate/v2_4/outputs_v24_demo"
```

输出路径只允许全新路径，已有空目录也不覆盖。程序不会下单、登录交易账户或上传本机数据。

## 6. 真实行情与旧结果核对

V2.3没有保存输入行情快照，现有几份汇总CSV不能重建旧行情或逐股票归因。
本版每次成功运行保存 `snapshot/` 和SHA256；再下载属于新快照，不声称精确复现旧26.09%的结果。
可选择与本机旧V2.3逐日净收益文件对比，输出日期是否一致及最大绝对差。
相同结果也不证明点时股票池正确；差异必须先排查数据和口径，再解释经济原因。

```bash
cd "$HOME/Downloads/QR_V24_separate/v2_4" && \
uv pip install --python .venv/bin/python -r requirements-download.txt && \
.venv/bin/python factor_audit_v2_4.py \
  --download --start 2018-01-01 --end 2025-01-01 --cost-bps 10 \
  --reference-v23 "$HOME/Downloads/QR_V23_separate/v2_3/outputs_v23_real_2018_2024" \
  --output outputs_v24_real_2018_2024
```

下载适配器只进行了模拟响应测试，此环境未执行真实Yahoo请求。yfinance1.8.0锁定依据用户已成功安装的版本，不是本机联网验证。
下载异常、漏日、漏股票、缺值会报错，不静默填价或删除股票。
结束日期不包含当天；end=2025-01-01覆盖2024最后交易日。

## 7. 输入快照重跑与重点输出

```bash
.venv/bin/python factor_audit_v2_4.py \
  --csv-dir outputs_v24_real_2018_2024/snapshot --output outputs_v24_replay
```

必需同日期/同股票顺序的 `close.csv` 与 `volume.csv`；可选 `source_close.csv`、`splits.csv`。
严格完整性检查不证明幸存者偏差消失。禁止为通过检查依据未来数据质量选择性删除证券。

优先检查：
- `comparison.csv`：动态、静态月调、静态买持及同股票池基准。
- `attribution.csv`：逐股票总损益/费用与累计收益贡献；另有逐日明细。
- `leave_one_out.csv`：全股票池逐一排除，而非只报告排除某个赢家。
- `definitions.csv`：运行与未运行的定义，明确未取得真实换手率。
- `RUN_INFO.json`：来源、参数、环境、所有结果哈希、旧版对比。

其余：`accounts/`完整交易与单位记录、`rank_ic.csv`、`concentration.csv`、`unit_stress.csv`、`split_audit.csv`。
只有本机重新跑过真实行情并核对快照后，才能讨论新实验的历史结果；人工演示数字不进入简历。
