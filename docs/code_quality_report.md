# 代码质量评估报告

> 生成日期：2026-07-18

## 总体评估：良好

经过多轮重构和补测后，代码库达到良好质量水平。工具链零警告，测试覆盖关键模块。

---

## 量化指标

| 指标 | 数值 |
|------|------|
| Python 源文件数（含 test） | 41 |
| Python 源文件数（非 test） | 32 |
| 总代码行数 | 8,383（有效代码 6,276） |
| 测试代码行数 | 2,107 |
| 测试数 | 292 |
| 测试通过率 | 100% |
| Ruff 警告数 | 0 |
| Pyright 错误数 | 0 |
| 总体测试覆盖率 | 87% |
| 函数含返回类型注解 | ~95% |

## 架构分层

```
app.py / collect_fund_data.py   # 入口点（Streamlit + CLI 采集）
db.py                           # 数据层（SQLAlchemy Core，10 张表）

backend/                        # 业务逻辑层
  ├─ dca_backtest.py            # 定投回测 CLI（参数解析/终端输出）
  ├─ dca_engine.py              # 定投回测引擎（数据加载/模拟核心）
  ├─ strategy.py                # 买入/卖出策略（固定金额/价值平均/均线/目标止盈/移动止盈）
  ├─ charting.py                # matplotlib 双面板图表
  ├─ cjk_font.py                # 中文字体检测与设置
  ├─ em_fetcher.py              # 东方财富 JS 直取
  ├─ formatters.py              # 格式化函数（百分率/净值/规模/综合费率）
  ├─ fund_data.py               # 基金数据共享层
  ├─ fund_query.py              # 基金查询逻辑
  ├─ index_fetcher.py           # 指数价格查询路由
  ├─ index_fund.py              # 指数选基后端
  ├─ index_valuation.py         # 指数估值后端
  ├─ logger.py                  # 统一日志配置
  ├─ parse_utils.py             # 字符串解析工具
  ├─ pension_fund.py            # 养老金选基后端
  └─ stats.py                   # 财务统计函数

tools/                          # CLI 工具
  ├─ build_index_name_map.py    # 指数名称→代码映射构造
  ├─ cnindex_export.py          # CNINDEX 数据导出
  ├─ compare_strategies.py      # 多策略对比
  ├─ csi_export.py              # 中证指数导出
  ├─ find_scenarios.py          # 场景化回测
  └─ gen_name_map_report.py     # 指数映射报告

app_pages/                      # Streamlit 页面
  ├─ dca.py                     # 定投回测
  ├─ fund_query.py              # 基金查询
  ├─ index_fund.py              # 指数选基
  ├─ index_valuation.py         # 指数估值
  └─ pension_fund.py            # 养老金选基

tests/                          # 测试套件（9 文件）
  ├─ conftest.py                # in-memory SQLite fixture
  ├─ test_db.py                 # DB 表操作（50 用例）
  ├─ test_dca_integration.py    # 定投集成（30 用例）
  ├─ test_formatters.py         # 格式化函数（34 用例）
  ├─ test_fund_classify.py      # 基金分类（21 用例）
  ├─ test_nav_history_cache.py  # 缓存策略（9 用例）
  ├─ test_parse_utils.py        # 解析工具（36 用例）
  ├─ test_stats.py              # 统计函数（48 用例）
  └─ test_strategy.py           # 策略类（39 用例）
```

## 优势

1. **测试覆盖大幅提升** — 从 30 用例 41% 覆盖到 292 用例 87% 覆盖，核心统计/格式化/策略/DB/解析模块达 88-100%
2. **Ruff + Pyright 零警告** — pre-commit 钩子强制执行
3. **统一日志** — `backend/logger.py` 消除散落的 `print()` 和静默吞异常
4. **数据层统一** — `db.py` OOP 化后表 API 一致，in-memory SQLite 可测试
5. **无循环依赖** — 模块依赖图无环
6. **模块职责清晰** — `dca_backtest.py` 拆分为 CLI + 引擎两层，各模块单一职责

## 可改进

| 问题 | 文件 | 说明 | 优先级 |
|------|------|------|--------|
| 25 处 `except Exception:` | 散落 `db.py` / `build_index_name_map.py` 等 | 已加 logger，仍可进一步缩小作用域 | 低 |
