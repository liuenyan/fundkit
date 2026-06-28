# fundkit 代码优化分析报告

## 🔴 Bug / 数据正确性

### 1. `db.py:117-127` — `fund_nav` 表主键缺失 `日期` 字段

当前主键仅为 `基金代码`，意味着同一只基金只能存一条净值记录。当前 `collect_fund_nav()` 是全表 replace 模式，所以不会丢数据，但若未来要存多条历史净值，这个 PK 设计就是 bug。

**建议**: 改为复合主键 `(基金代码, 日期)`。

### 2. `dca_backtest.py:105-136` — `fetch_fund_data` 完全绕过本地 DB 缓存

每次回测都调用两次 AKShare API（`fund_open_fund_info_em` × 2），即使 `db.fund_nav` 表已有缓存数据。回测必须联网且每次都很慢。

**建议**: 回测时优先读取本地 `fund_nav` 缓存，AKShare 作为兜底。

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

### 5. `collect_fund_data.py:229-257` — 两处逐行 `iterrows()` + `list.append()`

`open_df.iterrows()` 和 `etf_df.iterrows()` 逐行构建 `rows` 列表（`~25000` 只基金），Python 级循环性能差。

**建议**: 用 pandas vectorized 操作替代（如 `df.assign()` + 批量列操作）。

### 6. `dca_backtest.py:108-110` — 连续两次 AKShare API 调用获取净值

```python
df_unit = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
df_acc = ak.fund_open_fund_info_em(symbol=fund_code, indicator="累计净值走势")
```

两个独立 HTTP 请求获取互补数据，然后 merge。实际上两次请求的是同一个 JS 文件，只解析了不同变量。

**方案**: 自定义 `_fetch_nav_single()` — 一次 `requests.get(JS_URL)` + `py_mini_racer.eval()`，然后执行两次 `js.execute()` 提取 `Data_netWorthTrend` + `Data_ACWorthTrend`。HTTP 2→1，JS 解析 2→1。

---

## 🟡 代码冗余

### 7. `matplotlib.use("Agg")` 在 3 个文件中重复

- `backend/dca_backtest.py:15`
- `backend/charting.py:6`
- `app_pages/dca.py:16`

**建议**: 集中到一处（如 `tools/__init__.py` 或 `backend/__init__.py`），在进程启动时统一调用。

### 8. `sort_result()` 在 `fund_data.py` 和 `fund_query.py` 重复实现

- `backend/fund_data.py:296-306`
- `backend/fund_query.py:131-140`

两个函数逻辑几乎一致，但 `fund_query.py` 版多了 `na_position="last"`。

**建议**: 统一为一个共享函数。

### 9. 统计计算函数分散在两处

`dca_backtest.py` 的 `max_drawdown()`、`calc_annualized()` 是 CLI 专属，但逻辑与估值页的百分位计算有重叠潜力。

**建议**: 抽取通用统计函数到共享模块（如 `tools/formatters.py`）。

---

## 🟡 设计问题

### 10. `db.init_db()` 被频繁调用，每次执行 `create_all`

`init_db()` 调用 `metadata.create_all(engine)`，底层发 SQL `CREATE TABLE IF NOT EXISTS`。在 Streamlit UI 的每次页面加载中多次触发。

受影响位置:
- `backend/index_fund.py:78`
- `backend/index_valuation.py:120`
- `backend/pension_fund.py:50`
- `backend/fund_query.py:49`
- `collect_fund_data.py:35, 106, 196, 322`

**建议**: 使用 `lru_cache` 或全局 `_initialized` 标志，确保只执行一次。

### 11. `fund_nav` 表是全量快照（全表 replace）设计

`_BulkTable.save()` 用 `if_exists="replace"`，每采集一次就清空全表重写。对于 25000+ 只基金的日频数据，未来数据量增长后效率低。

**建议**: 改为增量 upsert 模式，仅插入/更新新数据。

### 12. `simulate_dca()` 单函数过长（127 行）

`dca_backtest.py:242-368` — 同时处理买入、卖出、分红再投、记录生成，逻辑混合。

**建议**: 拆分为子函数：
- `process_dividend()`
- `process_buy()`
- `process_sell()`
- `record_snapshot()`

---

## 🟢 小优化

### 13. `filter_funds()` 中多余的 `.copy()`

`backend/index_fund.py:154`: `result = df.copy()` 后立即筛选。`df` 未被修改，`copy()` 无实际必要。

### 14. `nav_dict` 构建可简化

`dca_backtest.py:252`:

```python
nav_dict = dict(zip(nav_df["date"], nav_df["unit_nav"]))
```

可直接用 `nav_df.set_index("date")["unit_nav"].to_dict()`。

### 15. `collect_fund_data.py:68-75` — 多线程闭包无锁

`_persist()` 闭包中 `nonlocal success, failed` 的递增操作在 `ThreadPoolExecutor` 中未加锁。虽 CPython GIL 保护了整数赋值，但语义不清晰。

**建议**: 使用 `threading.Lock` 包装，或改用 `queue.Queue` 收集结果。

---

## 优先级建议

| 优先级 | 问题编号 | 影响 |
|--------|----------|------|
| P0 | #1, #2 | 数据正确性 / 功能可用性 |
| P0 ~~#3~~ | ~~估值数据准确性~~ | ✅ 已完成 |
| P1 | ~~#4~~, #5, #6 | 性能瓶颈 |
| P1 | #10 | 启动效率 |
| P2 | #7, #8, #9, #12 | 可维护性 |
| P3 | #11, #13, #14, #15 | 未来优化 |
