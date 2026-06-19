# 数据源调研

## 当前活跃数据源

### 1. 中证指数 (csindex) — 主要 PE/价格数据源

| 字段 | 可用性 |
|------|--------|
| PE（滚动市盈率） | ✅ `stock_zh_index_hist_csindex()` |
| 价格（点位） | ✅ 同一接口的 `收盘` 列 |
| PB（市净率） | ❌ csindex 不提供 |
| 股息率 | ⚠️ `stock_zh_index_value_csindex()` 仅返回 20 行近期快照，含 `股息率1`/`股息率2` |

**API:** `stock_zh_index_hist_csindex(symbol, start_date, end_date)`
- 返回列：`日期`, `收盘`, `滚动市盈率` 等
- 全历史数据，最早至 2005 年

**估值快照 API:** `stock_zh_index_value_csindex(symbol)`
- 返回列：`市盈率1`, `市盈率2`, `股息率1`, `股息率2`
- **仅返回近 20 行**，无法获取历史序列
- 当前用于校准 payout_ratio，结合历史 PE 估算历史股息率

---

### 2. 乐咕乐股 (legulegu.com) — PB/补充 PE 数据源

| 字段 | 可用性 |
|------|--------|
| PE（滚动市盈率） | ✅ `stock_index_pe_lg()` |
| PB（市净率） | ✅ `stock_index_pb_lg()` |
| 价格（点位） | ✅ `stock_index_pe_lg()` 返回的 `指数` 列 |
| 股息率 | ❌ 不提供 |

**已知问题:**
- 站点间歇性不稳定（504/403），CSRF token 提取在超时时会失败
- 2026-06 验证：沪深300 PB 5149 行、中证500 PB 4720 行、创业板50 PB 4040 行，均已恢复

---

### 3. 国债收益率 — 十年期国债

**API:** `bond_zh_us_rate()` → `中国国债收益率10年` 列
- 6109 行（2002-01-04 ~ 至今）

---

## 已调研但不可行的数据源

### 4. 且慢 (qieman.com/idx-eval)

| 项目 | 结果 |
|------|------|
| 技术架构 | React SPA，所有数据通过 JS 运行时加载 |
| 公开 API | 不存在（SPA 壳 + JS bundle，API 调用不可见） |
| MCP API | 存在但需 API Key 注册（`stargate.yingmi.com/mcp/v2`） |
| 可行性 | ❌ 不适合。MCP API 主要提供基金分析/组合诊断，不直接提供指数估值序列 |

### 5. 蛋卷基金 (danjuanfunds.com/rn/value-center)

| 项目 | 结果 |
|------|------|
| 技术架构 | Next.js SPA，客户端渲染 |
| API 端点 | `djapi/v2/*`（如 `/djapi/v2/value-center`, `/djapi/v2/index/valuation`） |
| 认证要求 | 均需 `xq_a_token` cookie，未认证返回 `300001: 请重新登录` |
| 可行性 | ❌ 不适合。所有 API 需用户登录态，无法匿名访问 |

### 6. 雪球 (xueqiu.com)

| 项目 | 结果 |
|------|------|
| API 端点 | `/stock/valuation/index/{code}.json`, `/v5/stock/valuation/index/{code}.json` |
| 认证要求 | 400/403 需登录 |
| 可行性 | ❌ 不适合。同蛋卷，需登录态 |

---

## 股息率处理方案

中证红利（000922）的**历史股息率**无法从任何已知公开源直接获取，当前采用以下估算方案：

1. 调用 `stock_zh_index_value_csindex("000922")` 获取最新快照（20 行）
2. 取最新行的 `股息率1 (dp1)` 和 `市盈率1 (pe1)`，计算 `payout_ratio = dp1 × pe1 / 100`
3. 假设 payout_ratio 在历史上恒定（或缓慢变化），对 csindex PE 历史序列应用：
   `历史股息率 = payout_ratio / 历史PE × 100`
4. 生成约 3572 行日频股息率估算数据（2011~至今）

**误差来源：** payout_ratio 假设恒定，实际会因成分股调整和分红政策变化而波动。

---

## 数据源选择矩阵

| 需求 | 主要数据源 | 备选/补充 | 质量 |
|------|-----------|-----------|------|
| PE 历史序列 | csindex | Legulegu（指数级） | 高 |
| PB 历史序列 | Legulegu | — | 高（站点稳定时） |
| 指数价格/点位 | csindex | Legulegu | 高 |
| 十年期国债收益率 | `bond_zh_us_rate()` | — | 高 |
| 股息率（当前值） | csindex 快照 | — | 高 |
| 股息率（历史序列） | PE + payout_ratio 估算 | — | 中（有估算误差） |
