# 海外指数映射方案

## 背景

目前 `index_name_map` 覆盖中证 + 国证 + 海外共 491 条权益指数。
35 条失败项中大部分为海外指数（恒生系列、标普系列、纳斯达克、日经、富时等），
本方案规划海外指数的代码映射与价格数据获取。

## 可用数据源调研

### Sina 财经（稳定 ✅ → 主数据源）

| 接口 | 覆盖范围 | 已验证 symbol | 数据区间 | 本环境 |
|------|---------|---------------|---------|--------|
| `stock_hk_index_daily_sina` | 香港恒生系列 | HSI / HSCEI / HSTECH / HSCCI / CES100/300/120 / GEM | 2013~ | ✅ 可用 |
| `index_us_stock_sina` | 美股指数 | .INX / .IXIC / .DJI / .NDX / .SOX | 2004~ | ✅ 可用 |
| `stock_zh_index_daily` | A股指数（补充） | sh/sz 代码 | 依指数而异 | ✅ 可用 |

输出列格式（HK 和 US 通用）：`['date', 'open', 'high', 'low', 'close', 'volume', 'amount']`

### EM 东方财富（不稳定 ❌ → 候选，不依赖）

`index_global_hist_em` 理论上覆盖标普500/日经225/恒生指数/DAX/CAC/富时100/BOVESPA 等全球指数，
但本环境直连 `push2his.eastmoney.com` 持续 ConnectionError，偶尔成功。
若后续网络修复可纳入，当前不作为主数据源。

## 失败项分类

35 条海外失败项按获取难度分三层：

| 层级 | 可同时映射代码+价格 | 数量 | 说明 |
|------|--------------------|------|------|
| **P0** | 是 | 5 | 恒生指数/科技/国企 + 纳斯达克100 + 道琼斯 |
| **P1** | 代码映射 + acc_nav 回退 | ~10 | 日经/富时/DAX/CAC/BOVESPA 等，无免费价格源 |
| **P2** | 不处理 | ~19 | 标普系列细分子指数、恒生港股通细分、华证系列等，过于定制 |

### P0（可映射 + 可取价格）

| tracking target | normalize (KNOW_MAP key) | Sina symbol | index_code | short_name |
|----------------|--------------------------|-------------|------------|------------|
| 恒生指数 | 恒生 | HSI | HSI | 恒生指数 |
| 恒生中国企业指数 | 恒生中国企业 | HSCEI | HSCEI | 恒生国企 |
| 恒生科技指数 | 恒生科技 | HSTECH | HSTECH | 恒生科技 |
| 纳斯达克100指数 | 纳斯达克100 | .NDX | .NDX | 纳指100 |
| 道琼斯工业平均指数 | 道琼斯工业平均 | .DJI | .DJI | 道琼斯 |

> `market_prefix` 为 `None`（Sina symbol 在 `index_code` 中已完整，无需拼接）

### P1（仅代码映射，价格回退 acc_nav）

| tracking target | normalize | index_code | short_name |
|----------------|-----------|------------|------------|
| 恒生综合中型股指数 | 恒生综合中型股 | — | — |
| 恒生综合小型股指数 | 恒生综合小型股 | — | — |
| 东京日经225指数 | 东京日经225 | ^N225 | 日经225 |
| 伦敦富时100指数 | 伦敦富时100 | ^FTSE | 富时100 |
| 法兰克福DAX指数 | 法兰克福DAX | ^DAX | DAX |
| 法国CAC40指数 | 法国CAC40 | ^CAC | CAC40 |
| 巴西BOVESPA | 巴西BOVESPA | ^BVSP | BOVESPA |
| 恒生港股通50指数 | 恒生港股通50 | — | — |
| 恒生中国(香港上市)30指数 | 恒生中国30 | — | — |
| 恒生消费指数 | 恒生消费 | — | — |
| 恒生医疗保健指数 | 恒生医疗保健 | — | — |
| 恒生生物科技指数 | 恒生生物科技 | — | — |
| 恒生互联网科技业指数 | 恒生互联网科技业 | — | — |
| ... | ... | ... | ... |

### P2（维持失败，回退 acc_nav）

- 恒生细分行业（A股专精特新、A股电网设备、港股通创新药精选 等约 15 条）
- 标普系列细分（标普500信息科技、标普中国A股红利100 等 17 条）
- 纳斯达克细分（纳斯达克生物科技、纳斯达克科技市值加权 等 2 条）
- 道琼斯细分（道琼斯美国石油、道琼斯美国REIT 等 2 条）
- 新华系列（新华中诚信红利价值、新华沪港深新兴消费品牌 等 2 条）
- 华证系列（11 条，决定暂不处理）
- 非权益类错归类（中证5年恒定久期国开债、大商所豆粕、彭博利率债 等）

## 实施步骤

### Step 1：KNOWN_MAP 新增恒生 + 美股 P0 条目

source 标记新增类型 `sina_hk` 和 `sina_us`。`market_prefix` 设为 `None`（Sina symbol 在 `index_code` 中已完整）。
示例：

```python
"恒生":              ("HSI", None, "sina_hk", "equity", "恒生指数"),
"恒生中国企业":      ("HSCEI", None, "sina_hk", "equity", "恒生国企"),
"恒生科技":         ("HSTECH", None, "sina_hk", "equity", "恒生科技"),
"纳斯达克100":      (".NDX", None, "sina_us", "equity", "纳指100"),
"道琼斯工业平均":   (".DJI", None, "sina_us", "equity", "道琼斯"),
```

### Step 2：实现统一取价入口 index_fetcher.py

已在 `backend/index_fetcher.py` 实现：

```python
def fetch_index_price(index_code: str, source: str) -> pd.DataFrame | None:
    return get_or_update_series(index_code, "price", source,
                                 lambda: _fetch(source, index_code))[0]
```

内部按 source 路由：
- `source="csindex"` → `stock_zh_index_hist_csindex(index_code)`
- `source="sina_hk"` → `stock_hk_index_daily_sina(index_code)`
- `source="sina_us"` → `index_us_stock_sina(index_code)`

价格数据缓存于 `index_series` 表，`index_code` 列统一用裸码。

### Step 3：P1 仅代码映射

KNOWN_MAP 新增，source 标记 `accnav`，运行时直接回退基金自身 acc_nav。

### Step 4：P2 不予映射

维持现状，`classify_tracking_target` 中无变化的仍归类 `equity`，
运行时由 `fetch_fund_data()` 回退到 `fund_nav_history.acc_nav`。

## 数据源分布预期

```
现有:   csindex=486 + sina_hk=3 + sina_us=2 = 491
P1后:   csindex=486 + sina_hk=3 + sina_us=2 + accnav≈15 = ~500
最终:   csindex=486 + sina_hk=3 + sina_us=2 + accnav≈15 → 失败≈15
```

## 风险

- **Sina 限频**：`stock_hk_index_daily_sina` 无显式限频，建议 `time.sleep(0.3)`，首次调用较慢（~1s）
- **恒生/美股 code 变更**：低概率，AKShare 内部映射发生变化时需更新
- **EM 后续恢复**：可增加 `index_global_hist_em` 路由覆盖日经225/DAX/CAC 等
- **`stock_zh_index_daily` vs `stock_zh_index_hist_csindex`**：后者是官方主源，前者作为后备；验证发现 000922 中证红利在 `stock_zh_index_daily` 仅到 2019-01-30，`stock_zh_index_hist_csindex` 有完整数据
