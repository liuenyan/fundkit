# 优化方向

基金定投回测工具 fundkit 的综合优化方向，按优先级排列。  
已完成的用 [x] 标记。

---

## P1 — 健壮性与可观测性

### 静默吞异常

`db.py` 及其他后端模块约 15 处使用了 `except Exception: return None` 模式。DB 操作（查询、写入）失败时不报错、不记录，用户在 Streamlit 界面上看到的是空数据，无法区分是"无数据"还是"查询出错"。

**改进**：至少记录 warning 日志，对用户可见的错误应通过 Streamlit 的 `st.error` 或自定义异常向上传播。

### 无结构化日志

仅 `backend/index_fetcher.py` 一处使用 Python `logging`，其余模块（`db.py`、`collect_fund_data.py`、`backend/fund_data.py` 等）要么 `print()` 到 stdout，要么静默吞异常。生产环境问题排查困难。

**改进**：引入统一的 `logging` 配置，关键流程（采集、缓存命中/过期、查询失败）输出结构化日志。

### 数据库备份手动

`data/fundkit.db.bak.*` 是一个手动备份，无自动备份轮转策略。数据库一旦损坏或误写入错误数据，无法自动恢复。

**改进**：采集流程中增加自动备份，保留最近 N 个版本。

### 大结果集无分页

`app_pages/fund_query.py` 加载全部基金数据到内在 Python 侧截取前 50 条显示。全市场 >27,000 只基金的全部信息（费率、规模、档案等）每次查询都要全量加载。

**改进**：在 SQL 层加分页（LIMIT/OFFSET），或利用 Streamlit 的 `st.dataframe` 自带虚拟滚动显示全部结果。

### 回测指标增强

- [x] 当前仅输出收益率，已增加：最大回撤 / 年化波动率 / Sharpe 比率 / Calmar 比率
- 可进一步增加：胜率 / 盈亏比 / 盈利交易占比
- 在 `compare_strategies` 报告和 UI 展示中做更全面的横向对比

### 数据基础设施

- **`fund_nav` 缓存定时自动刷新**：当前需手动 `collect_fund_data.py --nav`
- **指数 PE 数据本地缓存**：`stock_index_pe_lg` 当前每次实时拉取 AKShare
- **成分股清单本地化**：中证指数成分股清单落地，支撑自算行业指数 PE（替代 Wind/Choice）

---

## P2 — 测试与质量保证

### 测试覆盖率 41%

按模块拆分：

| 模块 | 覆盖率 | 说明 |
|------|--------|------|
| `backend/strategy.py` | 98% | [x] 策略对象已充分测试 |
| `backend/parse_utils.py` | 95% | [x] Parse 工具函数已充分测试 |
| `backend/index_fund.py` | 62% | 搜索/筛选逻辑未测试 |
| `backend/pension_fund.py` | 67% | 分类逻辑未测试 |
| `backend/dca_backtest.py` | 46% | CLI main、绘图、数据获取未测试 |
| `db.py` | 42% | 大部分 save/load/clear 方法未测试 |
| `backend/index_valuation.py` | 17% | 几乎未测试 |
| `backend/stats.py` | 16% | 全部财务统计函数未测试 |
| `backend/index_fetcher.py` | 24% | API 路由未测试 |
| `backend/fund_data.py` | 10% | 几乎未测试 |
| `backend/em_fetcher.py` | 22% | JS eval 拉取器未测试 |
| `backend/formatters.py` | 0% | 完全未测试 |
| `collect_fund_data.py` | 0% | 完全未测试 |
| `app_pages/*` | 0% | 全部 UI 页面未测试 |
| `tools/*` | 0-13% | 全部工具未测试 |

**已覆盖的测试**（120 条）：
- `TargetProfitSellStrategy` — 触发/不触发/循环 3 条
- `TrailingStopSellStrategy` 回撤触发路径 — 停投→回撤卖出 1 条
- `ValueAveragingBuyStrategy` 最大倍数限制 / 最小金额兜底 — 2 条
- `MovingAverageBuyStrategy` 自定义 tier 路径 — 2 条
- `calc_redeem_fee()` / `calc_lumpsum()` / `generate_dca_dates()` 等 — 19 条

**改进**：
- 优先覆盖 IO/DB 模块的基础操作测试
- 为 UI 页面加集成测试
- 覆盖 `tools/compare_strategies.py`、`find_scenarios.py`、`formatters.py`、`stats.py`

### CI 未强制覆盖率门槛

`.github/workflows/ci.yml` 中 `pytest` 运行测试但未使用 `--cov-fail-under`，覆盖率下降不会被 CI 拦截。

**改进**：设置合理的覆盖率门槛（如 30%），配合 `--cov` 报告。

---

## P3 — 架构与可扩展性

### 无 HTTP API

当前仅提供 CLI 入口（5 个命令）和 Streamlit Web UI。外部服务、自动化脚本或用户自定义工具无法以编程方式调用回测、查询基金数据、获取指数估值。

**改进**：引入 FastAPI 层，暴露 RESTful API（如 `GET /backtest`、`GET /funds`、`GET /valuation`），便于集成和自动化。

### 无 Docker 化

项目依赖特定 Python 版本（>=3.11）、AKShare（需要网络和运行时 JS 引擎）、中文字体（matplotlib 绘图）等环境要求。当前无容器化方案，部署到新机器需要手动配置环境。

**改进**：提供 `Dockerfile`，将 CLI 和 Streamlit 服务都容器化，支持 `docker compose up` 一键启动。

### 策略完善

- [x] **指数价格 MA（Level 2）**：通过 `stock_zh_index_daily_em` + `fund_profile.跟踪标的` 获取底层指数日线计算均线，比基金 acc_nav 更纯净（不受分红、份额拆分干扰）。新增 CLI `--index-ma` 参数，加载指数日线代替基金净值计算 MA
- [x] **自定义 tier/multiplier 可配置化**：`MovingAverageBuyStrategy` 的 5 档偏差阈值和买入倍数改为 CLI/UI 参数
- **多信号组合策略**：MA 偏离度 + PE 百分位（宽基）/ 移动止盈 的信号叠加

### UI 增强

- [x] `app_pages/dca.py`：展示每次定投的 MA 偏离度、决策档位（如"偏离 -8.2% → 1.5x"）
- **策略对比结果直接在 UI 中可视化**：当前仅 CLI markdown 输出
- **回测报告导出为 PDF/HTML**

### 文档一致性

`README.md` 写 "Python 3.9+"，但 `pyproject.toml` 要求 `>=3.11`。

**修复**：统一文档中的 Python 版本要求。

### 参数扫描 / 优化器

- 对 MA `period`（60/120/250/500）、`tiers` 阈值、买入倍数做网格搜索
- 自动输出 Pareto 最优参数组合，报表格式类似 `compare_strategies`
