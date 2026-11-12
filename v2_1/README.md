# 多因子回测 V2.1 — 独立时间顺序验证版

> **版本标记：V2.1 / TIMING VALIDATION ONLY / GROSS PROXY**
>
> 这是新增的独立版本目录，不覆盖原代码、原数据或原图。所在分支为 `fix/v2.1-timing`；main 不变，未自动合并。仓库根目录旧 README 的 Sharpe、IR 和收益图不是本版验证结果。

## 来源与交付范围

原项目：`ace-wenda-li/multi-factor-backtest`。参考提交：`9f8b17e8e451aca45afe98a3a1cdd9729056e9d2`，主要依据 `backtest_260112.py`。本版为在用户授权下借助 ChatGPT 完成的修订与测试，发布日期为 2026-11-12。

主程序、完整测试文件、依赖文件与先前 V2.1 下载包逐字节一致；本次新增或更新的是 GitHub 入口、运行说明和验证记录。校验值见 [SOURCE_MANIFEST.json](SOURCE_MANIFEST.json)。

这是 standalone 文件，返回 `BacktestResult`，不是原函数的同签名替换。请运行本目录的 `backtest_v2_1.py`，不要运行旧脚本后把输出称作 V2.1。

**交付内容：完整运行源码、31 项离线测试、依赖文件及验证记录。** 旧下载包中自动生成的人工 CSV、XML 等输出不全部提交到 Git；人工行情及诊断 CSV 可用 `--demo` 离线生成。不需要这些预生成文件也能运行全部测试。

## 三项核心修复

### 每日横截面缩尾与标准化

保留四个因子公式及等权合成：20 日动量、负的 20 日波动率、20 日平均成交量的 log1p、负的 5 日收益。`turnover` 键仅保留原命名，它实际是成交股数指标，不是流通股换手率。

对每个交易日使用当日股票横截面的均值 ±3 个样本标准差缩尾，再根据缩尾后横截面计算 z-score。`mean(axis=1)` 跨股票计算；`clip/sub/div` 中 `axis=0` 用于日期对齐。不使用全样本时间均值或标准差。

至少两个已观察值完全相同时，已观察值记为零，缺失值仍为 NaN；仅一个有效值或全部缺失时不产生有效排名。四个因子必须都有效才得到综合评分。横截面标准化是本项目的建模选择；滚动时间序列标准化需要单独设计，不能使用未来样本。

### 真实交易月末

使用 `exchange_calendars` 的 XNYS 日历确定月末最后一个交易日。自然月末为周末或休市日时不会漏掉整个月；样本只到月中时不会把末行当成月末。样本首日至末日之间缺少完整交易日会报错，而不是误认为休市。

XNYS 是此美股研究使用的日历假设，不代替其他市场或个股停牌处理。

### 信号、成交和收益分开

月末 T 日收盘后生成信号；下一交易日 T+1 收盘成交；新持仓首次收益为 T+1 收盘至 T+2 收盘，记在 T+2。换仓日的收盘到收盘收益属于旧组合。

`weights_after_close[t]` 是 t 日收盘后的目标权重；`weights_for_return[t] = weights_after_close[t-1]`。首次建仓前持有现金，现金收益暂设为零。主组合与五分层共用时间规则。最后一个持仓区间持续计算至样本末日。无有效新信号时保留旧组合，不删除收益区间。

手算例子：A 在信号日、执行日、之后一天收盘价分别为 100、200、220。新仓位以 200 建仓，执行日不能赚到 100→200；之后一天收益为 220/200−1=10%。

## 尚未解决的限制

**输出 `gross_equal_weight_proxy` 是每日等权毛收益近似，不是真实月度固定股数持仓净收益。** 当月选定股票内仍假设每天无摩擦恢复等权，未追踪自然权重漂移。

- V2.2：权重漂移、成交金额、实际换手和交易费用。本版停用旧费用算法，非零 `cost_bps` 会报错。
- V2.3：Sharpe、IR、回撤、IC 等统计口径。本版不输出或认证这些绩效结论。
- 固定股票池的幸存者/选择偏差仍存在；复权行情的历史时点可得性未验证。
- 未完成完整公司行动、停牌、滑点和成交概率处理；下一交易日收盘成交仍是建模假设。
- 已选中或持有股票价格无效时明确报错，不自动补价、删除收益日或根据未来数据重新选股。
- 没有执行真实 Yahoo 数据下载或重新认证 2018–2024 年收益。演示数据全部人工生成。

通过测试只支持所覆盖的代码性质，不证明全部偏差已消除，也不证明策略盈利。

## 在 Mac 上获取与运行

### 克隆到新的本地文件夹

在 Terminal 中运行。目标目录若已存在且非空，git clone 会停止；不要为了继续运行而删除或覆盖已有项目。

```bash
cd "$HOME/Downloads"
git clone --branch fix/v2.1-timing --single-branch https://github.com/ace-wenda-li/multi-factor-backtest.git QR_V21_separate
cd QR_V21_separate/v2_1
```

也可在 GitHub 切换到 `fix/v2.1-timing` 分支，选择 Code → Download ZIP，解压后进入 `v2_1/`。整个分支会包含原文件；不要运行根目录旧脚本。

### 建立独立环境、测试、离线演示

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements-v2_1.txt
.venv/bin/python -m pytest -q tests
.venv/bin/python backtest_v2_1.py --demo --output outputs_demo
```

本次已在 Linux / Python 3.13.5 验证 31 项测试通过；你的 macOS / Python 3.11 环境需要本机确认。依赖文件固定直接依赖，不是完整的传递依赖锁文件。离线测试和演示不需要安装 yfinance。

输出目录必须不存在或为空，重复运行可改为 `--output outputs_demo_02`，避免覆盖旧结果。

### 使用本地 CSV

目录内需有 `close.csv` 和 `volume.csv`，第一列为日期，其余列为股票。日期及股票顺序一致，日期为无时区的交易日标签，不是盘中时间戳。

```bash
.venv/bin/python backtest_v2_1.py --csv-dir /你的行情目录 --output outputs_csv
```

### 可选：下载真实行情（尚未在交付环境验证）

```bash
uv pip install --python .venv/bin/python yfinance
.venv/bin/python backtest_v2_1.py --download --output outputs_real
```

下载失败或数据有问题时程序会报错，不会补造行情。下载成功会保存行情快照、版本及 CSV 哈希。默认日期保持原请求区间 `2018-01-01` 至 `2024-12-31`；end 不包含在内。要覆盖完整 2024 年可另设 `--end 2025-01-01`，但必须把区间变化单独记录。

## 先检查哪些输出

`schedule.csv` 记录信号日、成交日、首次收益日；`decision_log.csv` 记录选股和跳过原因。两份权重表用于核对收益归属。`gross_returns.csv` 仅供逻辑验证，不能作为简历中的净收益成绩。`run_metadata.json` 记录假设、数据来源标签、版本和文件哈希。

验证详情见 [validation/VALIDATION_REPORT.md](validation/VALIDATION_REPORT.md)。
