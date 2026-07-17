# 代码质量评估报告

> 生成日期：2026-07-17

## 总体评估：良好

经过多轮重构和补测后，代码库达到良好质量水平。工具链零警告，测试覆盖关键模块。

---

## 量化指标

| 指标 | 数值 |
|------|------|
| Python 源文件数（非 test） | 25 |
| 总代码行数 | 8,297（有效代码 6,738） |
| 测试代码行数 | 1,524 |
| 测试数 | 275 |
| 测试通过率 | 100% |
| Ruff 警告数 | 0 |
| Pyright 错误数 | 0 |
| 总体测试覆盖率 | 57% |
| 函数含返回类型注解 | ~95% |

## 架构分层

```
app.py / collect_fund_data.py   # 入口点（Streamlit + CLI 采集）
db.py                           # 数据层（SQLAlchemy Core，10 张表）

backend/                        # 业务逻辑层
  ├─ dca_backtest.py            # 定投回测核心（873 行，含 CLI main）
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
  ├─ test_dca_integration.py    # 定投集成（24 用例）
  ├─ test_formatters.py         # 格式化函数（34 用例）
  ├─ test_fund_classify.py      # 基金分类（21 用例）
  ├─ test_nav_history_cache.py  # 缓存策略（9 用例）
  ├─ test_parse_utils.py        # 解析工具（19 用例）
  ├─ test_stats.py              # 统计函数（48 用例）
  └─ test_strategy.py           # 策略类（39 用例）
```

## 优势

1. **测试覆盖大幅提升** — 从 30 用例 41% 覆盖到 275 用例 57% 覆盖，核心统计/格式化/策略/DB 模块达 88-100%
2. **Ruff + Pyright 零警告** — pre-commit 钩子强制执行
3. **统一日志** — `backend/logger.py` 消除散落的 `print()` 和静默吞异常
4. **数据层统一** — `db.py` OOP 化后表 API 一致，in-memory SQLite 可测试
5. **无循环依赖** — 模块依赖图无环

## 可改进

| 问题 | 文件 | 说明 | 优先级 |
|------|------|------|--------|
| ~~Layer 违规~~ | ~~`backend/index_fetcher.py:18` 从 `tools.build_index_name_map` 导入 `normalize()`~~ | ~~下层依赖上层~~ | ~~高~~ |
| ~~后端耦合 Streamlit~~ | ~~`fund_query.py`/`index_fund.py`/`pension_fund.py` 直接 `import streamlit`~~ | ~~无法脱离 UI 复用~~ | ~~高~~ |
| ~~MA 预热 buffer 复制粘贴~~ | ~~`dca_backtest.py:794` / `dca.py:233` / `compare_strategies.py:79`~~ | ~~15 行相同逻辑重复 3 次~~ | ~~高~~ |
| ~~NAV 列类型归一化重复 6 次~~ | ~~散落 `dca_backtest.py` / `dca.py` / `compare_strategies.py` / `find_scenarios.py`~~ | ~~缺 `normalize_nav_df()` 共享函数~~ | ~~中~~ |
| ~~`_SUFFIXES` / `normalize()` 重复~~ | ~~`build_index_name_map.py` / `cnindex_export.py` / `index_fund.py`~~ | ~~3 份独立副本~~ | ~~中~~ |
| `fmt_pct` 语义不一致 | `backend/formatters.py:10` vs `tools/compare_strategies.py:166` | 同名函数不同语义（% vs 原始值） | 中 |
| `SORT_OPTIONS` 各自定义 | `fund_data.py` / `fund_query.py` | 后者应复用前者 | 中 |
| `dca_backtest.py` 神级模块 | 873 行混合数据获取/模拟/绘图/CLI | 应拆分出 importable API | 低 |
| 25 处 `except Exception:` | 散落 `db.py` / `build_index_name_map.py` 等 | 已加 logger，仍可进一步缩小作用域 | 低 |
