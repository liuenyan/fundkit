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


def annualized_volatility(
    total_value: pd.Series,
    total_invested: pd.Series | None = None,
    dates: pd.Series | None = None,
) -> float:
    """年化波动率

    用 profit.diff() 剔除定投新增投入和分红的影响，
    并通过 dates 推断数据频率进行年化换算。
    """
    if total_invested is not None:
        profit = total_value - total_invested
        ret = profit.diff() / total_value.shift(1)
    else:
        ret = total_value.pct_change()
    ret = ret.dropna()
    if len(ret) < 2:
        return 0.0
    if dates is not None and len(dates) > 1:
        gap = max((dates.iloc[-1] - dates.iloc[0]).days / (len(dates) - 1), 1)
        periods_per_year = 365 / gap
    else:
        periods_per_year = 252
    return float(ret.std() * math.sqrt(periods_per_year))


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


def max_drawdown_duration(total_value: pd.Series, dates: pd.Series | None = None) -> int:
    """最大回撤持续期（自然日），dates 为 None 时返回数据点个数"""
    peak = total_value.expanding().max()
    underwater = total_value < peak
    streak = max_streak = streak_start = 0
    best_start = best_end = 0
    for i, val in enumerate(underwater):
        if val:
            if streak == 0:
                streak_start = i
            streak += 1
            if streak > max_streak:
                max_streak = streak
                best_start = streak_start
                best_end = i + 1
        else:
            streak = 0
    if max_streak == 0:
        return 0
    if dates is not None and best_end > best_start:
        return (dates.iloc[min(best_end, len(dates) - 1)] - dates.iloc[best_start]).days
    return max_streak
