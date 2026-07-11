---
name: backtest-core
description: 定投回测核心逻辑：策略类、simulate_dca 循环、赎回费计算、CLI 参数
---

## 策略体系 (`backend/strategy.py`)

### 买入策略
- **FixedBuyStrategy** `(amount, purchase_rate)` — 定期定额，date in invest_set 则买入固定金额
- **ValueAveragingBuyStrategy** `(target_value_increment, max_multiple=4.0, min_amount=10.0, purchase_rate=0.0015)` — 价值平均：每期增加固定市值，period_count 在 on_reset 时归零
- **MovingAverageBuyStrategy** `(base_amount, period, purchase_rate, nav_df, tiers=None, multipliers=None)` — 均线策略：偏离均线越远买入倍数越大。内置 3 种模式 (default/aggressive/conservative)，默认 tiers=(-0.1,-0.05,0,0.05), multipliers=(2,1.5,1,0.5,0)

### 卖出策略
- **TargetProfitSellStrategy** `(take_profit)` — 策略A：round_return >= take_profit → 全仓卖出
- **TrailingStopSellStrategy** `(stop_invest, trailing_stop)` — 策略B：先停投（round_return >= stop_invest → stop_buying），再移动止盈（回撤达 trailing_stop → 全仓卖出）

## simulate_dca 核心循环 (`backend/dca_backtest.py`)

逐行遍历 nav_df（全部交易日，chronological order）：
1. **分红再投**：date in dividend_dict → units += units * dividend_per_share / nav
2. **买入**：buy_strategy.should_buy(date, nav, pos, invest_set)，amount > 0 时 units += net / nav
3. **止盈判断**：sell_strategy.evaluate(...)，signal.stop_buying 设 pos.is_active=False，signal.should_sell 触发 _execute_sell
4. **记录**：仅当策略B启用 或 date in invest_set 或 有分红时生成当日快照

### 赎回费 `calc_redeem_fee(fee_batches, date, nav, redeem_schedule)`
每批份额有独立买入日期，按持有天数查档位费率累加。默认档位：`[(7, 1.5%), (30, 0.75%), (365, 0.5%), (730, 0.25%), (INF, 0%)]`

### 定投日期生成 `generate_dca_dates()`
向前最多搜索 10 个交易日，找不到则静默跳过。monthly 的 day 参数 clamp 到 28。

## CLI 参数 (`--help`)

```
必选: --fund --start
金额: --amount (定期定额) | --value-avg N (价值平均取代 --amount)
频率: --freq daily|weekly|biweekly|monthly  --day 1-28  --weekday 1-5
买入: 定期定额(默认) | 价值平均(--value-avg N --va-max-multiple 4 --va-min-amount 10)
策略A: --take-profit 0.20 --tp-cycle (循环止盈)
策略B: --stop-invest 0.20 --trailing-stop 0.08 (停投+移动止盈)
均线: --ma-period 250 (基金净值) | --ma-period 60 --index-ma (指数收盘价)
     --ma-mode default|aggressive|conservative
输出: --output path.csv --chart ./charts
```
