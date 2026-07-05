# 预采集工具 — `collect_fund_data.py`

批量采集基金数据写入 SQLite 数据库，为 Streamlit 页面提供零 API 冷启动能力。

## 用法

```bash
uv run python collect_fund_data.py [选项]
```

## 参数

| 参数 | 说明 |
|------|------|
| （无参数） | 采集费率 + 规模 + 档案 + 跟踪方式（默认） |
| `--force` | 强制全量重采（跳过 TTL 检查） |
| `--codes` | 指定基金代码，逗号分隔（仅采集指定基金） |
| `--workers` | 并发数，默认 10 |
| `--nav` | 仅采集净值（开放基 + ETF + FOF） |
| `--tracking-method` | 仅采集指数基金跟踪方式 |
| `--catalog` | 仅采集基金名录 |

## 示例

```bash
# 费率+规模+档案+跟踪方式（默认）
uv run python collect_fund_data.py

# 强制重采
uv run python collect_fund_data.py --force

# 仅采集净值
uv run python collect_fund_data.py --nav
uv run python collect_fund_data.py --nav --force

# 仅采集基金名录
uv run python collect_fund_data.py --catalog
uv run python collect_fund_data.py --catalog --force

# 仅采集跟踪方式
uv run python collect_fund_data.py --tracking-method

# 指定基金
uv run python collect_fund_data.py --codes 000001,161725
```

## 数据源与 TTL

| 数据 | API | TTL |
|------|-----|-----|
| 费率（申购/管理/托管/销售服务费） | `fund_purchase_em` + `fund_overview_em` | 90 天 |
| 规模（净资产/份额） | `fund_overview_em` | 90 天 |
| 档案（成立日/管理人/托管人/基金经理/基准/跟踪标的） | `fund_overview_em` | 90 天 |
| 净值（开放基） | `fund_open_fund_daily_em` | 24 小时 |
| 净值（ETF） | `fund_etf_fund_daily_em` | 24 小时 |
| 净值（FOF） | `fund_open_fund_rank_em` | 24 小时 |
| 基金名录 | `fund_name_em` | 90 天 |
| 跟踪方式 | `fund_info_index_em`（被动+增强两次调用） | —（无缓存，每次触发采集） |

## 写入表

- `fund_fee` — 申购费 / 管理费 / 托管费 / 销售服务费 / 综合费率 / 起购金额
- `fund_scale` — 净资产规模 / 份额规模
- `fund_profile` — 发行日期 / 成立日期 / 基金管理人 / 基金托管人 / 基金经理 / 业绩比较基准 / 跟踪标的 / 跟踪方式
- `fund_nav` — 单位净值 / 累计净值 / 日增长率（三源合并去重）
- `fund_catalog` — 基金代码 / 简称 / 类型（`fund_name_em` 全量）
- `funds_meta` — TTL 标记

## 工作流

```bash
# 初次使用（按顺序）
uv run python collect_fund_data.py --catalog   # 1. 基金名录
uv run python collect_fund_data.py              # 2. 费率+规模+档案+跟踪方式
uv run python collect_fund_data.py --nav         # 3. 净值

# 后续增量刷新
uv run python collect_fund_data.py --nav         # 仅刷新净值（24h TTL）

# 全量重置
uv run python collect_fund_data.py --force
uv run python collect_fund_data.py --nav --force
```
