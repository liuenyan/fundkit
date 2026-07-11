---
name: data-flow
description: 数据链路：采集流程、DB 表结构、缓存 TTL、AKShare API 映射
---

## 数据流架构

```
collect_fund_data.py → SQLite (data/fundkit.db) → Streamlit / CLI
所有 UI 页面通过 db.py 本地 JOIN 读取，运行时零 AKShare 调用
```

## 数据库表

| 表 | 主键 | 用途 |
|---|---|---|
| `fund_catalog` | 基金代码 | 全市场基金名录（27,037 只） |
| `fund_fee` | 基金代码 | 申/管/托/销 费率 + 起购金额 + 综合费率 |
| `fund_scale` | 基金代码 | 净资产规模 + 份额规模 |
| `fund_profile` | 基金代码 | 档案：成立日、基金经理、跟踪标的、跟踪方式 |
| `fund_nav` | 基金代码 | 最新净值快照（日频，24h TTL） |
| `fund_nav_history` | (基金代码, 日期) | 全量历史净值缓存（回测用，~9年 3273 条/基） |
| `fund_dividend` | (基金代码, 除息日) | 分红记录（每份分红金额） |
| `index_series` | (index_code, metric, date) | 指数估值时序：pe/pb/price/dividend_yield |
| `index_name_map` | display_name | 跟踪标的名称 → 指数代码/数据源/市场前缀 |
| `cache_meta` | (index_code, metric) | 指数缓存元信息 |
| `funds_meta` | key | 缓存 TTL 标记 |

## 缓存 TTL

| 数据 | TTL | 标记键 |
|------|-----|--------|
| fund_catalog | 24h | `funds_meta.key="fund_catalog"` |
| fund_fee | 90 天 | `funds_meta.key="fund_fee"` |
| fund_nav | 24h | `funds_meta.key="fund_nav"` |
| fund_dividend | 90 天 | `fund_dividend` 表 MAX(updated_at) |
| index_series | 2 天 | `cache_meta.last_updated` |
| fund_nav_history | 按需（is_cached 检查 MAX(日期)） |

## 数据源

| 数据 | AKShare API |
|------|-------------|
| 基金名录 | `fund_name_em()` |
| 申购费+起购 | `fund_purchase_em()` — 1 次批量调用 |
| 管理费/托管/销售服务费+规模+档案 | `fund_overview_em(symbol=code)` — 逐只并发（10 workers） |
| 净值（开放基金） | `fund_open_fund_daily_em()` — 1 次调用 |
| 净值（ETF） | `fund_etf_fund_daily_em()` — 1 次调用 |
| 历史净值 | `em_fetcher.fetch_nav_data(code)` — 解析东方财富 JS 文件 `pingzhongdata/{code}.js` |
| 跟踪方式(被动/增强) | `fund_info_index_em()` — 2 次调用（被动+增强） |

## 采集步骤

```bash
uv run collect --catalog     # 1. 基金名录（24h TTL）
uv run collect               # 2. 费率+规模+档案+跟踪方式（90d TTL）
uv run collect --nav         # 3. 净值快照（24h TTL）
```
