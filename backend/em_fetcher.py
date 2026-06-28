"""
东方财富网 pingzhongdata JS 数据直取层
"""

import requests
import pandas as pd
from py_mini_racer import MiniRacer

_JS_ENGINE = None


def _get_engine() -> MiniRacer:
    global _JS_ENGINE
    if _JS_ENGINE is None:
        _JS_ENGINE = MiniRacer()
    return _JS_ENGINE


def fetch_nav_data(fund_code: str) -> pd.DataFrame:
    """一次 HTTP 请求获取单位净值 + 累计净值 + 日增长率"""
    url = f"https://fund.eastmoney.com/pingzhongdata/{fund_code}.js"
    headers = {"Referer": "https://fund.eastmoney.com/"}
    r = requests.get(url, headers=headers)
    r.encoding = "utf-8"

    js = _get_engine()
    js.eval(r.text)

    raw_unit = js.execute("Data_netWorthTrend")
    df_unit = pd.DataFrame(raw_unit)
    df_unit["x"] = pd.to_datetime(df_unit["x"], unit="ms", utc=True).dt.tz_convert("Asia/Shanghai")
    df_unit["净值日期"] = df_unit["x"].dt.date
    df_unit["单位净值"] = pd.to_numeric(df_unit["y"], errors="coerce")
    df_unit["日增长率"] = pd.to_numeric(df_unit["equityReturn"], errors="coerce")

    raw_acc = js.execute("Data_ACWorthTrend")
    df_acc = pd.DataFrame(raw_acc, columns=["x", "累计净值"])
    df_acc["x"] = pd.to_datetime(df_acc["x"], unit="ms", utc=True).dt.tz_convert("Asia/Shanghai")
    df_acc["累计净值"] = pd.to_numeric(df_acc["累计净值"], errors="coerce")

    df = df_unit.merge(df_acc[["x", "累计净值"]], on="x", how="left")
    return df[["净值日期", "单位净值", "累计净值", "日增长率"]].copy()
