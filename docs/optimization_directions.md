# 优化方向

## A. 策略完善

- **[x] 指数价格 MA（Level 2）**：通过 `stock_zh_index_daily_em` + `fund_profile.跟踪标的` 获取底层指数日线计算均线，比基金 acc_nav 更纯净（不受分红、份额拆分干扰）。新增 CLI `--index-ma` 参数，加载指数日线代替基金净值计算 MA
- **[x] 自定义 tier/multiplier 可配置化**：`MovingAverageBuyStrategy` 的 5 档偏差阈值 (`DEFAULT_TIERS`) 和买入倍数 (`DEFAULT_MULTIPLIERS`) 改为 CLI/UI 参数
- **多信号组合策略**：MA 偏离度 + PE 百分位（宽基）/ 移动止盈 的信号叠加

## B. 测试覆盖

- **[x] `TargetProfitSellStrategy`** — 3 条（触发/不触发/循环）
- **[x] `TrailingStopSellStrategy` 回撤触发路径** — 1 条（停投→回撤卖出）
- **[x] `ValueAveragingBuyStrategy` 最大倍数限制 / 最小金额兜底** — 2 条（下跌多投/上涨少投）
- **[x] `MovingAverageBuyStrategy` 自定义 tier 路径** — 2 条（aggressive 超卖 / default 微低估）
- **[x] `calc_redeem_fee()` / `calc_lumpsum()` / `generate_dca_dates()` 等核心函数** — 19 条
- `tools/compare_strategies.py`、`find_scenarios.py`、`formatters.py`、`stats.py` — 无测试（暂不补）

## C. 回测指标增强

- 当前仅输出收益率，可增加：最大回撤 / 年化波动率 / Sharpe 比率 / Calmar 比率 / 胜率 / 盈亏比 / 盈利交易占比
- 在 `compare_strategies` 报告和 UI 展示中做更全面的横向对比

## D. 参数扫描 / 优化器

- 对 MA `period`（60/120/250/500）、`tiers` 阈值、买入倍数做网格搜索
- 自动输出 Pareto 最优参数组合，报表格式类似 `compare_strategies`

## E. UI 增强

- `app_pages/dca.py`：展示每次定投的 MA 偏离度、决策档位（如 "偏离 -8.2% → 1.5x"）
- 策略对比结果直接在 UI 中可视化（当前仅 CLI markdown 输出）
- 回测报告导出为 PDF/HTML

## F. 数据基础设施

- `fund_nav` 缓存定时自动刷新（当前需手动 `collect_fund_data.py --nav`）
- `stock_index_pe_lg` 数据本地缓存（当前每次实时拉取 AKShare）
- 中证指数成分股清单本地化，支撑自算行业指数 PE（替代 Wind/Choice）
