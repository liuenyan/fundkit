---
name: index-mapping
description: 指数名称映射与取价：KNOWN_MAP、CSI/CNINDEX 导出、取价路由、回调链
---

## 名称→代码映射体系

### 匹配优先级（`build_index_name_map.py`）
1. **KNOWN_MAP** — 手工兜底，15 条（含海外）
2. **CSI 官网导出**（`tools/csi_export.py`） → `data/csi_index_list.csv`，~1847 条股票类
3. **国证官网导出**（`tools/cnindex_export.py`） → `data/cnindex_index_list.csv`，~1212 条股票类

### KNOWN_MAP 条目（海外索引 market_prefix=None）

| display_name | code | source | 说明 |
|---|---|---|---|
| 恒生 | HSI | sina_hk | 恒生指数 |
| 恒生中国企业 | HSCEI | sina_hk | 恒生国企 |
| 恒生科技 | HSTECH | sina_hk | 恒生科技 |
| 恒生港股通新经济 | HSSCNE | hsi | 自定义 HSI API |
| 纳斯达克100 | .NDX | sina_us | — |
| 道琼斯工业平均 | .DJI | sina_us | — |

### market_prefix 规则
- `None` → 代码本身就是完整 Sina API symbol，无需拼接
- `sh` / `sz` / `csi` → 用于 daily_em API 拼接 `{prefix}{code}`
- `CN` 前缀代码 → `None`（全收益指数，无免费公开 API）

## 取价路由（`backend/index_fetcher.py`）

### `lookup_index(tracking_target) → (index_code, source, market_prefix) | None`
查询 `index_name_map` 表，返回路由信息。

### `fetch_index_price(index_code, source, market_prefix) → DataFrame | None`
调用 `_fetch_chain` 走缓存优先的 `get_or_update_series`。

### `_fetch_chain` 回调链
```
csindex → daily_em → sina_cn → None
sina_hk → None
sina_us → None
hsi → sina_hk → None
```
前一个源返回 None 则自动尝试下一个。

### `_fetch_one` 路由

| source | API | symbol 格式 |
|--------|-----|-------------|
| csindex | `stock_zh_index_hist_csindex` | 裸 code |
| daily_em | `stock_zh_index_daily_em` | `{prefix}{code}` |
| sina_cn | `stock_zh_index_daily` | `{prefix}{code}` |
| sina_hk | `stock_hk_index_daily_sina` | 裸 code |
| sina_us | `index_us_stock_sina` | 裸 code（含 `.`） |
| hsi | hsi.com.hk chart-rebased.json | 自定义 HTTP |

## 指数类型分类（`classify_tracking_target`）
- `bond` — 匹配 `中债`/`国债`/`可转债`/`债券` 等关键词
- `commodity` — 匹配 `上海金`/`黄金`/`原油`/`商品`
- `overseas` — 匹配 `纳斯达克`/`标普`/`道琼斯`/`恒生`/`MSCI` 等
- 默认 `equity`（非 equity 分类不写入 `index_name_map`）
