# fundkit 代码优化分析报告

## 🔴 Bug / 数据正确性

### 1. 缺少回测历史净值缓存 —— 新建 `fund_nav_history` 表 ✅

`fund_nav` 是全量快照表（覆写模式），不适合存储回测所需的全部历史净值。`fetch_fund_data()` 每次调用都访问 HTTP API。

**修复**: 新建 `fund_nav_history` 表，复合主键 `(基金代码, 日期)`；新增 `FundNavHistoryTable` 类（`is_cached`/`load`/`save`）；`fetch_fund_data()` 缓存优先。详见 `db.py:327-382`。

### 2. `dca_backtest.py` — `fetch_fund_data` 绕过本地缓存 + `sys.exit(1)` 异常处理粗糙 ✅

每次回测都调用 HTTP API 获取净值，且出错时直接 `sys.exit(1)`，Streamlit UI 只能靠 `SystemExit` 捕获。

**修复**: `fetch_fund_data` 缓存优先（cache-first），远程获取后自动写入 `fund_nav_history`。新增 `BacktestError` 异常替代 `sys.exit(1)`，CLI `main()` 统一 `try/except BacktestError → sys.exit(1)`，GUI 直接 `st.error() + st.stop()`。删除 `safe_call` 包装器。

### 3. `db.py:340-346` — `upsert_series()` 使用 `OR IGNORE` 而非 `OR REPLACE` ✅

```python
index_series.insert().prefix_with("OR IGNORE")
```

`OR IGNORE` 碰到同名同日期数据会**静默跳过**，导致旧值残留，影响估值百分位计算准确性。

**修复**: `OR IGNORE` → `OR REPLACE`，重复行不再静默跳过。

---

## 🟡 性能

### 4. `db.py:340-346` — `upsert_series()` 逐行 INSERT ✅

每行数据一个独立 SQL INSERT。指数估值历史数据（上千行）插入极慢。

```python
for _, row in df.iterrows():
    conn.execute(...)
```

**修复**: 改为构建 `data` list 后单次 `conn.execute(data)` 批量写入。

### 5. `collect_fund_data.py:229-257` — 两处逐行 `iterrows()` + `list.append()` ✅

`open_df.iterrows()` 和 `etf_df.iterrows()` 逐行构建 `rows` 列表（`~25000` 只基金），Python 级循环性能差。

**修复**: 三个循环全部替换为 `_build_nav_part()` 向量化构造 DataFrame，最终 `pd.concat()`。旧 scalar 函数 `_parse_daily_pct`/`_to_float` 替换为 series 版。ETF 源跳过差集（与 open 无交集），FOF 源保留差集去重。性能约 450ms → 40ms。

### 6. `dca_backtest.py:108-110` — 连续两次 AKShare API 调用获取净值 ✅

```python
df_unit = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
df_acc = ak.fund_open_fund_info_em(symbol=fund_code, indicator="累计净值走势")
```

两个独立 HTTP 请求获取互补数据，然后 merge。实际上两次请求的是同一个 JS 文件，只解析了不同变量。

**修复**: 新建 `backend/em_fetcher.py` — 一次 HTTP 请求 + 一次 JS eval，两次 `js.execute()` 分别提取 `Data_netWorthTrend` + `Data_ACWorthTrend`。HTTP 2→1，JS 解析 2→1。MiniRacer 实例模块级懒加载只初始化一次。

---

## 🟡 代码冗余

### 7. `matplotlib.use("Agg")` 在 3 个文件中重复 ✅

- `backend/dca_backtest.py:15`
- `backend/charting.py:6`
- `app_pages/dca.py:16`

**修复**: 集中到两个入口点（`app.py` + `backend/dca_backtest.py`），共享模块 `charting.py` 和页面模块 `dca.py` 移除。遵循 `use("Agg")` 必须在 `pyplot` import 之前的原则。

### 8. `sort_result()` 在 `fund_data.py` 和 `fund_query.py` 重复实现 ✅

- `backend/fund_data.py:296-306`
- `backend/fund_query.py:131-140`

两个函数逻辑几乎一致，但 `fund_query.py` 版多了 `na_position="last"`。

**修复**: `fund_data.sort_result` 增加 `sort_options` 参数 + `na_position="last"`；`fund_query.sort_result` 删除，`query_funds` 内联调用 `fund_data.sort_result`。

### 9. 统计计算函数分散在两处 ✅

`dca_backtest.py` 的 `max_drawdown()`、`calc_annualized()` 是 CLI 专属，但逻辑与估值页的百分位计算有重叠潜力。

**修复**: 新建 `tools/stats.py`，迁移三个函数。消除 `app_pages/dca.py` 从 `dca_backtest` import 统计函数的不合理依赖。

---

## 🟡 设计问题

### 10. `db.init_db()` 被频繁调用，每次执行 `create_all` ✅

`init_db()` 调用 `metadata.create_all(engine)`，底层发 SQL `CREATE TABLE IF NOT EXISTS`。在 Streamlit UI 的每次页面加载中多次触发。

受影响位置:
- `backend/index_fund.py:78`
- `backend/index_valuation.py:120`
- `backend/pension_fund.py:50`
- `backend/fund_query.py:49`
- `collect_fund_data.py:35, 106, 196, 322`

**修复**: 添加模块级 `_DB_INITIALIZED` 标志，`init_db()` 首次执行后跳过后续调用。每次进程最多一次 `create_all`。

### 11. `fund_nav` 表是全量快照（全表 replace）设计 ✅

`_BulkTable.save()` 用 `if_exists="replace"`，每采集一次就清空全表重写。对于 25000+ 只基金的日频数据，未来数据量增长后效率低。

**修复**: 改为 `DELETE FROM ...`（事务内）+ `if_exists="append"`，避免 DROP TABLE + 重建 schema 的开销。当前 snapshot 模型保留，待 #1 #2 联动时改增量 upsert。

### 12. `simulate_dca()` 单函数过长（127 行） ✅

`dca_backtest.py:242-368` — 同时处理买入、卖出、分红再投、记录生成，逻辑混合。

**修复**: 提取 `_execute_sell()`（卖出执行）和 `_build_record()`（记录构建）两个辅助函数，循环体从 90 行降至 55 行。

---

## 🟢 小优化

### 13. `filter_funds()` 中多余的 `.copy()` ✅

`backend/index_fund.py:154`: `result = df.copy()` 后立即筛选。`df` 未被修改，`copy()` 无实际必要。

### 14. `nav_dict` 构建可简化 ✅

`dca_backtest.py:252`:

```python
nav_dict = dict(zip(nav_df["date"], nav_df["unit_nav"]))
```

可直接用 `nav_df.set_index("date")["unit_nav"].to_dict()`。

### 15. `collect_fund_data.py:68-75` — 多线程闭包无锁 ✅

`_persist()` 闭包中 `nonlocal success, failed` 的递增操作在 `ThreadPoolExecutor` 中未加锁。

**分析**: `on_result` 回调实际在主线程串行执行（`as_completed` 迭代器在主线程 yield），无竞态。

**处理**: 加注释说明 `on_result` 在主线程串行执行，无需锁。

---

## 优先级建议

| 优先级 | 问题编号 | 影响 |
|--------|----------|------|
| P0 ~~#1, #2~~ | ~~回测历史缓存 + BacktestError~~ | ✅ 已完成 |
| P0 ~~#3~~ | ~~估值数据准确性~~ | ✅ 已完成 |
| P1 | ~~#4~~, ~~#5~~, ~~#6~~ | 性能瓶颈 |
| P1 | ~~#10~~ | 启动效率 |
| P2 | ~~#7~~, ~~#8~~, ~~#9~~, ~~#12~~ | 可维护性 |
| P3 | ~~#11~~, ~~#13~~, ~~#14~~, ~~#15~~ | 未来优化 |
