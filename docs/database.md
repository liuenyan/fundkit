# 数据库设计

数据库文件：`data/fundkit.db`，SQLite，WAL 模式。

## 表一览

| 表名 | 行数 | 用途 | 状态 |
|------|------|------|------|
| `fund_catalog` | 27,037 | 全市场基金名录 | ✅ 活跃 |
| `fund_fee` | 26,770 | 基金费率（申购/管理/托管/销售服务） | ✅ 活跃 |
| `fund_scale` | 26,505 | 基金规模（净资产/份额） | ✅ 活跃 |
| `fund_profile` | 26,770 | 基金基本信息/档案 | ✅ 活跃 |
| `fund_nav` | 25,333 | 基金最新净值（日频快照） | ✅ 活跃 |
| `fund_nav_history` | 3,273/基 | 基金全量历史净值（回测缓存） | ✅ 活跃 |
| `index_series` | 73,742 | 指数估值时序（PE/PB/点位） | ✅ 活跃 |
| `index_name_map` | 482 | 跟踪标的名称→指数代码映射 | ✅ 活跃 |
| `cache_meta` | 17 | 估值数据源元信息 | ✅ 活跃 |
| `funds_meta` | 3 | 缓存 TTL 标记 | ✅ 活跃 |

---

## `fund_catalog` — 基金名录

**来源**: `fund_name_em()`（天天基金网，27037 只全量）

| 列 | 类型 | 说明 |
|----|------|------|
| `基金代码` | TEXT PK | 6 位基金代码 |
| `拼音缩写` | TEXT | 拼音首字母缩写 |
| `基金简称` | TEXT | 基金名称（如"招商中证白酒指数(LOF)A"） |
| `基金类型` | TEXT | 分类（如"指数型-股票"、"FOF-稳健型"、"混合型"） |
| `拼音全称` | TEXT | 全拼音 |

**TTL**: 24 小时（`db.CATALOG_TTL`）
**刷新**: `collect_fund_data.py`（默认流程包含）

---

## `fund_fee` — 基金费率

**来源**: `fund_purchase_em()`（申购费）+ `fund_overview_em()`（管理/托管/销售服务费，逐只并发）

| 列 | 类型 | 说明 |
|----|------|------|
| `基金代码` | VARCHAR PK | 6 位基金代码 |
| `申购费` | FLOAT | 申购费率（%，如 `0.15`） |
| `管理费` | FLOAT | 管理费率（%，如 `1.20`） |
| `托管费` | FLOAT | 托管费率（%，如 `0.20`） |
| `销售服务费` | FLOAT | 销售服务费率（%，C 类通常有值） |
| `起购金额` | VARCHAR | 最低申购金额 |
| `综合费率` | FLOAT | 申购费+管理费+托管费+销售服务费之和 |
| `updated_at` | FLOAT | unix 时间戳 |

**TTL**: 90 天（`db.FEE_TTL`）
**刷新**: `collect_fund_data.py`（默认流程，`--force` 强制）

---

## `fund_scale` — 基金规模

**来源**: `fund_overview_em()`（逐只并发）

| 列 | 类型 | 说明 |
|----|------|------|
| `基金代码` | VARCHAR PK | 6 位基金代码 |
| `净资产规模` | FLOAT | 净资产规模（亿元），如 `26.44` |
| `份额规模` | FLOAT | 份额规模（亿份），净资产规模缺失时用于兜底（×单位净值） |
| `updated_at` | FLOAT | unix 时间戳 |

**TTL**: 24 小时（`db.SCALE_TTL`）
**刷新**: `collect_fund_data.py`（默认流程包含）

---

## `fund_profile` — 基金档案

**来源**: `fund_overview_em()`（逐只并发）+ `fund_info_index_em()`（跟踪方式）

| 列 | 类型 | 说明 |
|----|------|------|
| `基金代码` | VARCHAR PK | 6 位基金代码 |
| `发行日期` | VARCHAR | 基金发行日期 |
| `成立日期` | VARCHAR | 基金成立日期 |
| `基金管理人` | VARCHAR | 基金管理公司 |
| `基金托管人` | VARCHAR | 基金托管银行 |
| `基金经理` | VARCHAR | 现任基金经理 |
| `业绩比较基准` | VARCHAR | 业绩比较基准 |
| `跟踪标的` | VARCHAR | 跟踪指数（如"沪深300指数"） |
| `跟踪方式` | String | 指数基金：`被动指数型` / `增强指数型`（名称启发式兜底） |
| `updated_at` | FLOAT | unix 时间戳 |

**跟踪方式覆盖**: 6452 只指数基金零遗漏（API 采集+名称启发式兜底）
**刷新**: `collect_fund_data.py`（默认流程）+ `--tracking-method`

---

## `fund_nav` — 基金最新净值

**来源**: 三源融合

| 列 | 类型 | 说明 |
|----|------|------|
| `基金代码` | TEXT PK | 6 位基金代码 |
| `日期` | TEXT | 净值日期（如 `2026-06-18`） |
| `单位净值` | FLOAT | 最新单位净值 |
| `累计净值` | FLOAT | 最新累计净值（ETF/开放基/FOF 有值） |
| `日增长率` | FLOAT | 日增长率（百分数，如 `0.58` 表示 +0.58%） |
| `数据来源` | TEXT | `open` / `etf` / `fof`，标记数据来源 |
| `updated_at` | FLOAT | unix 时间戳 |

### 采集优先级

| 序号 | API | 覆盖 | 列名差异 |
|------|-----|------|----------|
| 1 | `fund_open_fund_daily_em()` | 23,529 只开放基金 | 动态列名 `{date}-单位净值`，日增长率为纯数字 |
| 2 | `fund_etf_fund_daily_em()` | 1,549 只场内 ETF | 动态列名，`增长率` 列带 `%` 后缀 |
| 3 | `fund_open_fund_rank_em(FOF)` | 975 只 FOF | 固定列名，日增长率为纯数字 |

写入规则：Source 2/3 仅写 Source 1 未覆盖的基金代码。

**TTL**: 24 小时（`db.NAV_TTL`）
**刷新**: `collect_fund_data.py --nav`（`--force` 强制）

### Y 份额覆盖（养老金选基）

| 类型 | 总数 | 覆盖 | 来源 |
|------|------|------|------|
| 指数型-股票 Y | 105 | 105 (100%) | Source 1 |
| FOF Y | 216 | 200 (93%) | Source 3 |
| **合计** | **321** | **305 (95%)** | |

缺失 16 只极新 FOF Y 份额，会在下次 API 刷新时自动补全。

---

## `fund_nav_history` — 基金全量历史净值（回测缓存）

**用途**: 定投回测 `fetch_fund_data()` 的本地缓存，避免每次回测都请求 HTTP API。

**来源**: `backend/em_fetcher.fetch_nav_data()` — 一次 HTTP 请求解析东方财富 JS 文件 `pingzhongdata/{code}.js`，返回全量历史（~9 年，~3273 条/基）。

| 列 | 类型 | 说明 |
|----|------|------|
| `基金代码` | TEXT PK | 6 位基金代码 |
| `日期` | TEXT PK | 净值日期（`YYYY-MM-DD`） |
| `单位净值` | FLOAT | 当日单位净值 |
| `累计净值` | FLOAT | 当日累计净值 |
| `日增长率` | FLOAT | 日增长率（百分数，如 `0.58` 表示 +0.58%） |
| `updated_at` | FLOAT | unix 时间戳 |

**主键**: `(基金代码, 日期)` — 同一只基金同一天只存一条。

### 缓存策略

`is_cached(fund_code, end_date)` 通过 `_last_available_data_day()` 确定 end_date 已知的最新交易日，与缓存 `MAX(日期)` 比较：

| 条件 | 回退交易日 | 举例 |
|------|-----------|------|
| `end_date` 是周末 | 本周五 | 周日→上周五 |
| 今天且 `now.hour < 22` | 上一个交易日 | 周三 09:00→周二 |
| 其他 | `end_date` 本身 | 周四(非今天)→周四 |

---

## `index_series` — 指数估值时序

**来源**: AKShare `stock_zh_index_value_csindex()` + `bond_zh_us_rate()` 等

| 列 | 类型 | 说明 |
|----|------|------|
| `name` | TEXT PK | 指数名称或代码 |
| `metric` | TEXT PK | 指标名（如 `pe`, `pb`, `close`, `dividend_yield`） |
| `date` | TEXT PK | 日期（`YYYY-MM-DD`） |
| `value` | FLOAT | 指标值 |

**典型 name 示例**: `000922`（中证红利）、`000016`（上证50）
**典型 metric 示例**: `pe`, `pb`, `close`, `dividend_yield_中证红利`
**TTL**: 2 天（`is_series_fresh` 检查）

---

## `index_name_map` — 跟踪标的名称→指数代码映射

**用途**: 将 `fund_profile.跟踪标的`（中文名称）解析为 CSI 指数代码，用于指数价格 MA（Level 2）策略。

**来源**: `tools/build_index_name_map.py`（一次性种子生成，后续按需更新）

| 列 | 类型 | 说明 |
|----|------|------|
| `display_name` | TEXT PK | 归一化后的指数名称（去掉"指数"/"(价格)"后缀），如 `沪深300` |
| `index_code` | TEXT NOT NULL | 指数数字代码，如 `000300` |
| `market_prefix` | TEXT | 市场标识：`sh` 上交所 / `sz` 深交所 / `csi` 中证 / `bj` 北交所 — 用于 `stock_zh_index_daily_em` 后备 |
| `source` | TEXT | 数据源：`csindex`（中证指数官网）/ `daily_em`（东方财富，国证系列后备） |
| `index_type` | TEXT NOT NULL | 指数类型：`equity`（权益，适用均线策略）/ `bond` / `commodity` / `overseas` |

### 构建逻辑

```
build_index_name_map.py:
  1. 读取 fund_profile 的全部 688 个唯一 跟踪标的
  2. 非权益关键词过滤（中债/标普/纳斯达克/恒生等 → index_type 分类）
   3. 名称归一化（去掉"指数""(价格)"及 `人民币`/`港元`/`美元`/`港币` 货币后缀）
   4. 四级匹配（优先级从高到低）：
      4a. KNOWN_MAP 手工兜底表（1条：上海金非权益）
      4b. csi_export.get_equity_name_map()（中证指数官网导出接口，5,471 条 equity 映射）
      4c. cnindex_export.get_equity_name_map()（国证指数官网导出接口，3,390 条 equity 映射，补深证/国证系列）
      4d. ak.index_stock_info() 精确匹配（数据源：聚宽 joinquant）
   5. 匹配结果写入 index_name_map
   6. 输出报告
```

> CSI 官网导出接口覆盖 中证/上证/沪深 系列（1847 条股票类）。国证官网导出接口覆盖 深证/国证 系列（1212 条股票类），两者互补。聚宽作为最终兜底。CNINDEX name_map 构建使用 `setdefault` 防止货币变体覆盖标准版代码。

当前覆盖：**482 条 equity**（常用宽基+行业+主题+沪港深指数），**39 条**无法匹配的偏门指数自动回退 acc_nav（Level 3）。

> 完整映射报告见 `docs/index_name_map_report.md`，可通过 `PYTHONPATH=. ./venv/bin/python tools/gen_name_map_report.py` 重新生成。

---

## `cache_meta` — 缓存元信息

| 列 | 类型 | 说明 |
|----|------|------|
| `name` | TEXT PK | 与 index_series.name 对应 |
| `metric` | TEXT PK | 与 index_series.metric 对应 |
| `last_updated` | TEXT | 最后更新日期 |
| `source` | TEXT | 数据源标记 |

---

## `funds_meta` — 缓存 TTL 标记

| 列 | 类型 | 说明 |
|----|------|------|
| `key` | TEXT PK | 缓存标识：`fund_catalog` / `fund_fee` / `fund_nav` |
| `value` | TEXT | 固定为 `"ok"` |
| `updated_at` | FLOAT | unix 时间戳，用于 TTL 比较 |

**记录数**: 3（fund_catalog, fund_fee, fund_nav）

---

## OOP 访问层

```python
# 所有表通过模块级单例访问，统一位于 db 模块下
from db import fund_fees, fund_scale, fund_profile, fund_nav, fund_catalog, fund_nav_history
```

### 类体系

```
_FundTable                  基类：is_fresh / set_fresh / clear
 ├── _DictTable             加载为 {code: dict}
 │    ├── FundFeeTable      db.fund_fees      meta_key="fund_fee"
 │    ├── FundScaleTable    db.fund_scale     meta_key=None
 │    └── FundProfileTable  db.fund_profile   meta_key=None
 └── _BulkTable             全表 DataFrame 操作
      ├── FundNavTable      db.fund_nav       meta_key="fund_nav"
      └── FundCatalogTable  db.fund_catalog   meta_key="fund_catalog"

FundNavHistoryTable         历史净值缓存（独立 OOP，异构接口）
     db.fund_nav_history    meta_key=None     is_cached / load / save
```

### 方法说明

| 方法 | _FundTable | _DictTable | _BulkTable | FundNavHistoryTable | 说明 |
|------|-----------|-----------|-----------|-------------------|------|
| `is_fresh(ttl)` | ✅ | 继承 | 继承 | — | 检查 `funds_meta` 的 `updated_at` 是否在 TTL 内 |
| `set_fresh()` | ✅ | 继承 | 继承 | — | 写入当前时间戳到 `funds_meta` |
| `clear()` | ✅ | 继承 | 继承 | — | `DELETE FROM 表` + 清理对应 `funds_meta` 记录 |
| `_load_rows(codes)` | — | ✅ | — | — | `SELECT * FROM 表 WHERE 基金代码 IN (codes)` 返回 `{code: Row}` |
| `load(codes)` | — | ✅ | — | — | 返回 `{code: {列名: 值, ...}}` |
| `load()` | — | — | ✅ | — | 返回全表 `DataFrame` |
| `save(df)` | — | — | ✅ | — | `df.to_sql(if_exists="replace")` + `set_fresh()` |
| `cached_count()` | — | FundFeeTable 独有 | — | — | `SELECT COUNT(*) FROM fund_fee` |
| `is_cached(code, end_date)` | — | — | — | ✅ | 检查缓存是否覆盖 `end_date` 已知最新交易日 |
| `load(code, start, end)` | — | — | — | ✅ | 读取指定基金/日期范围的净值 |
| `save(code, df)` | — | — | — | ✅ | OR REPLACE 批量写入全量历史 |

### 使用示例

```python
# dict 表
fees = db.fund_fees.load(["000001", "161725"])
# → {"000001": {"申购费": 0.15, "管理费": 1.2, ...}, ...}

db.fund_fees.save("000001", 0.15, 1.2, 0.2, None, "1元", 1.55)

db.fund_fees.is_fresh()        # 检查 fund_fee 缓存是否有效
db.fund_fees.set_fresh()       # 标记 fund_fee 缓存新鲜
db.fund_fees.cached_count()    # → 26770
db.fund_fees.clear()           # DELETE FROM fund_fee + DELETE FROM funds_meta WHERE key='fund_fee'

# bulk 表
nav = db.fund_nav.load()       # → DataFrame (25333 行)
db.fund_nav.save(df)           # 全量替换

cat = db.fund_catalog.load()   # → DataFrame (27037 行)

# freshness（meta_key=None 的表始终返回 False）
db.fund_scale.is_fresh()       # → False（不追踪 TTL）
```

### 保持为独立函数的操作

- `load_index_fund_nav()` — 5 表 JOIN（指数基净值+费率+规模+跟踪方式）
- `load_pension_funds()` — 4 表 JOIN（Y 份额基金）
- `load_series() / upsert_series() / is_series_fresh()` — 估值时序缓存
- `clear_all()` — 清空所有缓存表

