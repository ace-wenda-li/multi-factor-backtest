# V2.4 — Jupyter-first 实验入口（独立分支）

这是 **Jupyter 研究留档版**，基于已核实的 `fix/v2.4-factor-audit`，只新增 Notebook 与 Jupyter 环境说明，**不改动 V1–V2.4 任何回测引擎**。

## 日常工作方式

- 主入口：`v2_4/notebooks/V24_Factor_Audit_Research.ipynb`
- 在 Jupyter 逐格执行：环境校验 → 可选测试 → 数据模式设置 → 实验运行 → 图表 → 研究笔记。
- **File → Save Notebook** 保留输入代码、表格、图和你的文字解释；每次实验另存 `v2_4/outputs_jupyter/<timestamp>_<id>/`，包含价格、成交量、附属快照、账户、交易记录、绩效对比、归因、所有 CSV 的 SHA256 和运行元数据。
- 原始结果目录不覆盖；不要删除或重命名以前的结果。
- 人工数据只是代码检查，真实数据结果仍有固定股票池幸存者偏差等限制。V2.3 旧数据未保存完整快照，重新下载不能假定与旧结果精确相同。

## 只做一次的 Terminal 安装与 Kernel 注册

如果还没有克隆过 V2.4 的目录，使用 **全新** `QR_V24_Jupyter` 文件夹：

```bash
cd "$HOME/Downloads" && \
git clone --branch feat/v2.4-jupyter --single-branch \
  https://github.com/ace-wenda-li/multi-factor-backtest.git QR_V24_Jupyter && \
cd QR_V24_Jupyter/v2_4 && \
uv venv --python 3.11 .venv && \
uv pip install --python .venv/bin/python -r requirements-jupyter.txt && \
.venv/bin/python -m ipykernel install --user --name qr-v24-jupyter --display-name "Python (QR V2.4 Jupyter)"
```

注意如果文件夹 `QR_V24_Jupyter` 已存在，`git clone` 会拒绝写入，不要删除旧项目以继续。

## 打开 Jupyter

日常有两种方式：

1. **使用 VS Code（推荐如果已安装 Python/Jupyter 扩展）**：Open Folder → `~/Downloads/QR_V24_Jupyter`，打开 `v2_4/notebooks/V24_Factor_Audit_Research.ipynb`，右上角选择 `Python (QR V2.4 Jupyter)`。
2. 使用 JupyterLab：首次或需要启动服务时在 Terminal 运行：

```bash
cd "$HOME/Downloads/QR_V24_Jupyter" && v2_4/.venv/bin/jupyter lab
```

在浏览器中打开该 Notebook，右上角选择上述 Kernel。用完保存 Notebook，终端 `Ctrl+C` 结束服务。

## 研究过程（尽量不回 Terminal）

在 Notebook 第 2 单元格可将 `RUN_TESTS=True`，自动执行 pytest，并将结果显示在该单元格。

在参数单元格将 `MODE` 选择 `demo` / `download` / `csv`：

- 第一次运行先用 `demo` 检查流程。
- 真实行情用 `download`，可使用锁定的 yfinance 依赖（见 requirements-jupyter）；需要网络，结果是**新快照**。
- 同一批行情复现用 `csv`，指向先前输出的 `snapshot/` 目录，不联网，尽量保持可重复。

Notebook 会用新的时间戳加随机后缀生成输出目录；不会覆盖历史目录。详细步骤和研究提纲都在 Notebook Markdown 单元格内。

### 本版本承诺

不修改任何旧分支或脚本，不自动向 GitHub 推送输出数据。不要把本版本的回顾性结果描述为独立样本外 Alpha；真实流通股换手率未检验；收益贡献不等于单股 CAGR 或因果 Alpha 归因。
