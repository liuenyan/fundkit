# 优化方向

基金定投回测工具 fundkit 的综合优化方向，按优先级排列。  
已完成的用 [x] 标记。

---

## P1 — 健壮性与可观测性

### 静默吞异常

- [x] `db.py` 及其他后端模块约 15 处使用了 `except Exception: return None` 模式。已逐处添加 `logger.warning/error`，DB 操作失败时会输出日志到 stderr 和文件，用户可通过 Streamlit 的 `st.error` 或自定义异常向上传播。

### 无结构化日志

- [x] 仅 `backend/index_fetcher.py` 一处使用 Python `logging`。已创建 `backend/logger.py` 统一日志配置，所有模块使用 `get_logger(__name__)`，同时输出到 stderr 和 `data/fundkit.log`（5MB × 3 轮转），入口点（CLI main / Streamlit app）调用 `setup_logging()`。

### 共享 API 中使用 `print()` 而非 `logger`

`backend/dca_engine.py:57,76` 中 `fetch_fund_data()` 使用 `print()` 输出加载状态。此函数被 Streamlit UI 调用，`print()` 仅输出到终端，用户在 Web 界面看不到反馈，且日志文件也无记录。

**改进**：改为 `logger.info()`，同时在 `app_pages/dca.py` 包装层用 `st.status` 或 `st.toast` 提供 UI 反馈。

### 数据库备份手动

`data/fundkit.db.bak.*` 是一个手动备份，无自动备份轮转策略。数据库一旦损坏或误写入错误数据，无法自动恢复。

**改进**：采集流程中增加自动备份，保留最近 N 个版本。

### 大结果集无分页

`app_pages/fund_query.py` 加载全部基金数据到内在 Python 侧截取前 50 条显示。全市场 >27,000 只基金的全部信息（费率、规模、档案等）每次查询都要全量加载。

**改进**：在 SQL 层加分页（LIMIT/OFFSET），或利用 Streamlit 的 `st.dataframe` 自带虚拟滚动显示全部结果。

- [ ] 当前非性能瓶颈（SQLite 全量加载 ~200ms / 缓存后 <10ms），等用户反馈加载慢时再处理。

### 回测指标增强

- [x] 当前仅输出收益率，已增加：最大回撤 / 年化波动率 / Sharpe 比率 / Calmar 比率
- [x] 胜率 / 盈亏比 / 最大回撤持续期 — `backend/stats.py` 已实现，CLI 和 UI 均已展示
- 在 `compare_strategies` 报告和 UI 展示中做更全面的横向对比

### 数据基础设施

- **`fund_nav` 缓存定时自动刷新**：当前需手动 `collect_fund_data.py --nav`
- **指数 PE 数据本地缓存**：`stock_index_pe_lg` 当前每次实时拉取 AKShare
- **成分股清单本地化**：中证指数成分股清单落地，支撑自算行业指数 PE（替代 Wind/Choice）

---

## P2 — 测试与质量保证

### 测试覆盖率 87%（较此前 57% 大幅提升）

按模块拆分：

| 模块 | 覆盖率 | 说明 |
|------|--------|------|
| `backend/strategy.py` | 100% | [x] 策略对象已充分测试 |
| `backend/parse_utils.py` | 97% | [x] Parse 工具函数已充分测试 |
| `backend/formatters.py` | 100% | [x] 格式化函数已充分测试 |
| `backend/stats.py` | 100% | [x] 财务统计函数已充分测试 |
| `db.py` | 88% | [x] 表 Save/Load/Clear/缓存/Join 查询已覆盖 |
| `backend/index_fund.py` | 62% | 搜索/筛选逻辑未测试 |
| `backend/pension_fund.py` | 67% | 分类逻辑未测试 |
| `backend/dca_engine.py` | — | 新拆分模块 |
| `backend/index_valuation.py` | 17% | 几乎未测试 |
| `backend/index_fetcher.py` | 24% | API 路由未测试 |
| `backend/fund_data.py` | 11% | 几乎未测试 |
| `backend/em_fetcher.py` | 22% | JS eval 拉取器未测试 |
| `collect_fund_data.py` | 0% | 完全未测试 |
| `app_pages/*` | 0% | 全部 UI 页面未测试 |
| `tools/*` | 0-13% | 全部工具未测试 |

**已覆盖的测试**（292 条）：
- `stats.py` 9 个纯函数 — 48 条
- `formatters.py` 4 个格式化函数 — 34 条
- `strategy.py` 全部策略类 — 39 条
- `db.py` 表访问层、Join 查询、缓存、清理函数 — 50 条
- `test_dca_integration.py` 分红/模拟/赎回费集成 — 30 条
- `parse_utils.py` 工具函数 — 36 条

**改进**：
- [x] 覆盖 IO/DB 模块的基础操作测试（formatters.py / stats.py / db.py / strategy.py）
- [x] 新增 `test_parse_utils.py` 36 条（normalize / normalize_nav_df）
- 为 UI 页面加集成测试
- 覆盖 `tools/compare_strategies.py`、`find_scenarios.py`

### `collect_fund_data.py` 整体不可测试

| 问题 | 详情 |
|------|------|
| 测试覆盖 | 0% — 全文件无测试 |
| 日志 | 全文件使用 `print()`，无 `logger` |
| 过长函数 | 3 个函数均 >120 行（`collect_tracking_method` 127 行 / `collect_fund_nav` 122 行 / `collect_fund_catalog` 122 行） |
| 增量更新 | 每次全量拉取，网络开销大 |

**改进**：
- 用 `logger` 替换 `print()`
- 拆分过长函数，将网络请求 / 数据转换 / 写入分离
- 设计增量采集策略（基于 fund_nav 最大日期）

### CI 未强制覆盖率门槛

`.github/workflows/ci.yml` 中 `pytest` 运行测试但未使用 `--cov-fail-under`，覆盖率下降不会被 CI 拦截。

**改进**：设置合理的覆盖率门槛（如 30%），配合 `--cov` 报告。

### 17/27 模块无专用测试文件

后端 + 工具共 27 个非测试 Python 文件，仅 4 个有同名专用测试文件（`formatters` / `parse_utils` / `stats` / `strategy`）。缺少专用测试的模块包括：

| 影响较大 | 影响较小 |
|----------|----------|
| `dca_engine.py`（核心模拟，依赖集成测试间接覆盖） | `charting.py`（纯 matplotlib 渲染） |
| `fund_data.py`（11% 覆盖，费率 ETL） | `logger.py`（单次配置调用） |
| `em_fetcher.py`（JS eval 拉取器） | `cjk_font.py`（字体检测） |
| `index_fetcher.py`（24% 覆盖，API 路由） | `tools/*`（CLI 脚本） |

**改进**：按影响面分批补充。优先 `dca_engine.py` 和 `fund_data.py`。

---

## P3 — 架构与可扩展性

### 过长函数（圈复杂度）

以下函数超过 80 行，混合了多个职责，可读性和可测试性偏低：

| 文件 | 函数 | 行数 | 混合的职责 |
|------|------|------|-----------|
| `db.py` | `_FundTable` 类 | 186 | 所有表的 init/save/load/clear/exists |
| `backend/fund_data.py` | `enrich_fee_scale` | 161 | 费率 + 规模 ETL + 数据校验 |
| `backend/dca_engine.py` | `calc_lumpsum` | 140 | 一次性投入 + 分红再投资 + 每日明细 |
| `backend/dca_backtest.py` | `main` | 81 | CLI 参数校验 + 策略构造 + MA 计算内联 |

**改进**：拆分单一职责，参照 `dca_backtest.py` 的拆法（`main` 中的 MA 计算可抽出独立函数）。

### 22 个函数缺少返回类型注解

分布在 `dca_engine.py`（11 个）、`dca_backtest.py`（4 个）、`fund_data.py`（3 个）、`collect_fund_data.py`（1 个）等。pyright standard mode 不报错（ruff 中 `ANN` 被 `ignore`），不影响运行，但降低 IDE 推断精度和代码可读性。

**改进**：批量补全返回类型注解。

### 硬编码魔术值

| 位置 | 值 | 建议 |
|------|-----|------|
| `app_pages/dca.py:72` | `.head(20)` | 提取为 `SEARCH_LIMIT` 模块级常量 |
| `backend/dca_backtest.py:81` | `--chart default="./charts"` | 使用 `pathlib` |
| `db.py` | `_FundTable` 硬编码列名字符串 | 可改为声明式表定义 |

**改进**：提取为命名常量，统一管理。

### 无 HTTP API

当前仅提供 CLI 入口（5 个命令）和 Streamlit Web UI。

- [ ] 不引入 FastAPI / REST API，原因：
  - Streamlit 已覆盖所有交互场景（5 页面）
  - CLI 已覆盖自动化场景（Shell 脚本可直接调用）
  - 加 API 层需 uvicorn + streamlit 双进程部署，复杂度翻倍
  - 无外部消费者（个人定投研究工具）

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

- [x] `README.md` 写 "Python 3.9+"，但 `pyproject.toml` 要求 `>=3.11`。已统一为 3.11+。

### 参数扫描 / 优化器

- 对 MA `period`（60/120/250/500）、`tiers` 阈值、买入倍数做网格搜索
- 自动输出 Pareto 最优参数组合，报表格式类似 `compare_strategies`
