"""金融统计函数"""

import math

import pandas as pd


def max_drawdown(series: pd.Series) -> float:
    peak = series.expanding().max()
    dd = (series - peak) / peak
    return dd.min()


def calc_annualized(ret: float, start: pd.Timestamp, end: pd.Timestamp) -> float:
    days = (end - start).days
    if days <= 0:
        return 0.0
    return (1 + ret) ** (365 / days) - 1


def calc_percentile(series: pd.Series) -> float | None:
    s = series.dropna()
    if len(s) < 2:
        return None
    return float((s < s.iloc[-1]).mean() * 100)


def annualized_volatility(total_value: pd.Series) -> float:
    daily_ret = total_value.pct_change().dropna()
    return float(daily_ret.std() * math.sqrt(252))


def sharpe_ratio(annualized_ret: float, annualized_vol: float, risk_free: float = 0.0) -> float:
    if annualized_vol == 0:
        return 0.0
    return (annualized_ret - risk_free) / annualized_vol


def calmar_ratio(annualized_ret: float, mdd: float) -> float:
    if mdd == 0:
        return 0.0
    return annualized_ret / abs(mdd)


def win_rate(return_rate: pd.Series) -> float:
    positive = (return_rate > 0).sum()
    total = return_rate.notna().sum()
    return positive / total if total > 0 else 0.0


def profit_loss_ratio(return_rate: pd.Series) -> float:
    gains = return_rate[return_rate > 0]
    losses = return_rate[return_rate < 0]
    if gains.empty or losses.empty:
        return 0.0
    return float(gains.mean() / abs(losses.mean()))


def max_drawdown_duration(total_value: pd.Series) -> int:
    peak = total_value.expanding().max()
    underwater = total_value < peak
    streak = max_streak = 0
    for val in underwater:
        if val:
            streak += 1
        else:
            if streak > max_streak:
                max_streak = streak
            streak = 0
    return max(max_streak, streak)
