# 定投回测指标定义与计算方法

## 基础指标

### 总收益率 (Total Return)

最终实际到账金额相对于总投入的收益率。

```
Total Return = (final_val - total_invested) / total_invested
```

- `final_val`: 期末市值 - 赎回费 + 历史止盈净到账
- `total_invested`: 全部定投期数投入金额之和（含申购费）
- **已实现** — 由 `simulate_dca` 直接返回

### 年化收益率 (Annualized Return)

将总收益率折算为年化形式，假设复利。

```
Annualized Return = (1 + Total Return) ^ (365 / days) - 1
```

- `days`: 首期定投日与最后一笔交易日之间的自然日数
- **已实现** — `backend/stats.py:calc_annualized()`

---

## 风险指标

### 最大回撤 (Max Drawdown)

组合市值（`total_value`）从历史高点回撤的最大幅度，衡量策略在最差情况下的亏损。

```
MDD = min((total_value - peak) / peak)
peak = expanding max of total_value
```

- 使用 `total_value`（含已止盈回收金额）作为观察序列
- 正值表示回撤幅度（如 0.25 表示最大亏 25%）
- **已实现** — `backend/stats.py:max_drawdown()`

### 年化波动率 (Annualized Volatility)

组合市值日收益率的年化标准差，衡量策略收益的波动剧烈程度。

```
daily_returns = total_value.pct_change().dropna()
Annualized Volatility = std(daily_returns) * sqrt(252)
```

- 252 = A 股年化交易日数
- 日收益率使用 `total_value` 序列计算，而非基金净值
- **待实现**

### 最大回撤持续期 (Max Drawdown Duration)

从净值创下新高到恢复至该高点所经过的最长天数。

```
DD_start = date of peak
DD_end  = date when total_value >= peak
Duration = DD_end - DD_start (自然日)
```

反映策略从亏损中恢复所需的最长时间，与最大回撤共同衡量尾部风险。
- **待实现**

---

## 风险调整收益指标

### Sharpe 比率 (Sharpe Ratio)

每承担一单位总风险所获得的超额收益。

```
Sharpe = (Annualized Return - Rf) / Annualized Volatility
```

- `Rf`: 无风险利率，默认取 **0%**（或可配置为 10 年期国债收益率）
- 使用年化后的分子分母，结果也是年化值
- 通常 > 1 可接受，> 2 良好，> 3 优秀
- **待实现**

### Calmar 比率 (Calmar Ratio)

每承担一单位最大回撤风险所获得的年化收益。

```
Calmar = Annualized Return / |MDD|
```

- 与 Sharpe 互补：Sharpe 衡量"平均"波动风险，Calmar 衡量"最差"回撤风险
- 通常 > 1 可接受，> 2 良好，> 3 优秀
- **待实现**

---

## 交易统计指标

### 胜率 (Win Rate)

所有观察日中组合处于盈利状态的比例。

```
Win Rate = count(return_rate > 0) / count(return_rate != 0)
```

- `return_rate` 取自 detail DataFrame 的每一行快照
- 排除 `total_invested == 0` 的空仓日
- 反映策略在时间维度上的"舒适度"，非财务意义
- **待实现**

### 盈亏比 (Profit/Loss Ratio)

盈利日平均收益率与亏损日平均收益率（绝对值）之比。

```
avg_gain = mean(return_rate)  for return_rate > 0
avg_loss = mean(|return_rate|) for return_rate < 0
P/L Ratio = avg_gain / avg_loss
```

- 反映盈利的质量：值越大表示每次赚的比赔的多
- 结合胜率可计算期望收益：`Win Rate * avg_gain - (1 - Win Rate) * avg_loss`
- **待实现**

### 盈利交易占比 (Profitable Cycles / Trades)

在有止盈策略的场景下，已完成轮次中盈利轮次占比。

```
Profitable Cycles Ratio = profitable_cycles / total_completed_cycles
```

- 仅适用于使用 `--tp-cycle` 或策略B循环模式的场景
- 一次性定投（无止盈循环）的场景该指标无意义
- **待实现**

---

## 数据来源说明

所有指标的计算基于 `simulate_dca` 返回的以下数据：

| 数据 | 来源 | 说明 |
|------|------|------|
| `total_value` | detail 表 | 持仓市值 + 已止盈回收金额 |
| `total_invested` | detail 表 | 累计总投入 |
| `return_rate` | detail 表 | `(total_value - total_invested) / total_invested` |
| `final_val` | simulate_dca 直接返回 | 最终实际到账（期末市值 - 赎回费 + 历史止盈净到账） |
| events | simulate_dca 直接返回 | 止盈事件列表，每笔含盈亏 |
| `invest_dates` | generate_dca_dates | 定投执行日期序列 |

完整指标列表：

| 指标 | 状态 | 所在函数 |
|------|------|----------|
| 总收益率 | ✅ 已实现 | `simulate_dca` 返回 + 外部计算 |
| 年化收益率 | ✅ 已实现 | `calc_annualized()` |
| 最大回撤 | ✅ 已实现 | `max_drawdown()` |
| 年化波动率 | ❌ 待实现 | — |
| 最大回撤持续期 | ❌ 待实现 | — |
| Sharpe 比率 | ❌ 待实现 | — |
| Calmar 比率 | ❌ 待实现 | — |
| 胜率 | ❌ 待实现 | — |
| 盈亏比 | ❌ 待实现 | — |
| 盈利交易占比 | ❌ 待实现 | — |
