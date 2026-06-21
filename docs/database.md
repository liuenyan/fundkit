# 数据库设计

数据库文件：`data/fundkit.db`，SQLite，WAL 模式。

## 表一览

| 表名 | 行数 | 用途 | 状态 |
|------|------|------|------|
| `fund_catalog` | 27,037 | 全市场基金名录 | ✅ 活跃 |
| `fund_fee` | 26,770 | 基金费率（申购/管理/托管/销售服务） | ✅ 活跃 |
| `fund_scale` | 26,505 | 基金规模（净资产/份额） | ✅ 活跃 |
| `fund_profile` | 26,770 | 基金基本信息/档案 | ✅ 活跃 |
| `fund_nav` | 25,333 | 基金最新净值 | ✅ 活跃 |
| `index_series` | 73,742 | 指数估值时序（PE/PB/点位） | ✅ 活跃 |
| `cache_meta` | 17 | 估值数据源元信息 | ✅ 活跃 |
| `funds_meta` | 3 | 缓存 TTL 标记 | ✅ 活跃 |
| `funds` | 4,578 | 旧缓存（已废弃，待清理） | ❌ 废弃 |

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

## 废弃表

### `funds`

旧版基金缓存表，已被 `fund_nav` + `fund_fee` + `fund_profile` + `fund_scale` 四表取代。代码依赖已全部移除，仅数据库中存在，可安全删除。

### `fund_fees`（已删）

旧版费率缓存表，仅含管理费/托管费 2 列，已被 `fund_fee` 表取代。已从数据库中 DROP。
