# 代码质量评估报告

> 生成日期：2026-06-28

## 总体评估：良好

经过多轮重构后，代码库达到良好质量水平。明显重复已消除，架构分层清晰，工具链零警告。

---

## 量化指标

| 指标 | 数值 |
|------|------|
| Python 源文件数（非 test） | 22 |
| 总代码行数 | 3,812 |
| 函数总数（非 test） | 127 |
| 含返回类型注解的函数 | 108（85%） |
| 类总数 | 20 |
| Ruff 警告数 | 0 |
| 测试数 | 30 |
| 测试通过率 | 100% |

## 架构分层

```
collect_fund_data.py    # 数据预采集（费率/规模/档案/净值/名录/跟踪方式）
db.py                   # 数据层（OOP，10 张表，含 fund_nav_history 缓存）
tools/                  # 公用工具
  ├─ cjk_font.py        # 中文字体检测与设置
  ├─ formatters.py      # 格式化工具
  └─ stats.py           # 统计函数（max_drawdown / calc_annualized / calc_percentile）
backend/                # 业务逻辑层
  ├─ charting.py        # matplotlib 双面板图表（CLI/UI 共享）
  ├─ dca_backtest.py    # 定投回测核心（cache-first，BacktestError 异常）
  ├─ em_fetcher.py      # 东方财富 JS 直取（一次 HTTP + JS eval 获取全量净值）
  ├─ strategy.py        # 买入/卖出策略基类 + 4 种内置实现（9 个类）
  ├─ fund_query.py      # 基金查询逻辑
  ├─ fund_data.py       # 共享层（费率解析、规模兜底、sort_result）
  ├─ index_fund.py      # 指数选基后端
  ├─ index_valuation.py # 指数估值后端
  └─ pension_fund.py    # 养老金选基后端
app_pages/              # Streamlit UI（5 页，与 st.navigation 一致）
  ├─ dca.py             # 定投回测
  ├─ fund_query.py      # 基金查询
  ├─ index_fund.py      # 指数选基
  ├─ index_valuation.py # 指数估值
  └─ pension_fund.py    # 养老金选基
tests/
  ├─ test_fund_classify.py      # 分类逻辑（21 用例）
  └─ test_nav_history_cache.py  # 缓存策略（9 用例）
```

## 优势

1. **零重复模式** — 多轮重构清除了十余处重复代码，提取共享函数到 `tools/` 和 `backend/fund_data.py`
2. **Ruff 零警告** — 代码风格完全一致（line-length=120, py311）
3. **测试覆盖** — 分类逻辑 + 缓存策略共 30 个纯函数测试，全部通过
4. **数据层统一** — `db.py` OOP 化后表单例 API 一致，冷启动零 API 调用
5. **历史净值缓存** — `fund_nav_history` 表 + `_last_available_data_day` 缓存策略，回测 2 次请求变为 0（缓存命中时）
6. **错误处理统一** — `BacktestError` 异常替代 `sys.exit(1)`，CLI 与 GUI 统一处理路径
7. **文件体积合理** — 最大文件 612 行（`dca_backtest.py`），其余 < 600 行

## 可改进

| 问题 | 文件 | 说明 | 建议 |
|------|------|------|------|
| 部分函数缺返回类型注解 | 19 处（`strategy.py` 基类、`db.py` save、`dca_backtest.py` 辅助函数等） | 多数是 `-> None` 隐式返回或 `-> Self`，当前 ruff ANN 规则未强制 | 低优先级，不影响运行 |
| 测试覆盖偏窄 | `tests/` 仅 2 文件 | 仅覆盖分类逻辑和缓存策略，回测核心、DB 操作、页面前端未覆盖 | 中优先级，核心路径优先 |
| `fund_nav_history` 表无 TTL 清理 | `db.py` | 历史缓存随回测使用持续积累，无自动清理机制 | 低优先级，需手动 `DELETE` |
