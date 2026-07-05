"""金融统计函数"""

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
