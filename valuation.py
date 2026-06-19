"""
指数估值百分位计算 + 历史百分位序列
数据源: 中证指数 (中证公司发布) 优先，乐咕乐股 (其他指数) 备用
"""

import logging
from datetime import datetime

import numpy as np
import pandas as pd
import akshare as ak

from cache import get_or_update_series

logger = logging.getLogger(__name__)
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.WARNING,
)

_TODAY = datetime.now().strftime("%Y%m%d")

CONFIG = [
    {"name": "沪深300", "source": "csindex", "param": "000300",
     "pb": True, "pb_source": "index_lg", "pb_param": "沪深300"},
    {"name": "中证500", "source": "csindex", "param": "000905",
     "pb": True, "pb_source": "index_lg", "pb_param": "中证500"},
    {"name": "中证红利", "source": "csindex", "param": "000922"},
    {"name": "红利低波", "source": "csindex", "param": "H30269"},
    {"name": "CS消费50", "source": "csindex", "param": "931139"},
    {"name": "创业板50", "source": "index_lg", "param": "创业板50",
     "pb": True, "pb_source": "index_lg", "pb_param": "创业板50"},
]

VALUATION_BANDS = [(0, 30, "低估"), (30, 70, "适中"), (70, 100, "高估")]


def calc_percentile(series):
    s = series.dropna()
    if len(s) < 2:
        return None
    return float((s < s.iloc[-1]).mean() * 100)


def get_label(pct):
    if pct is None:
        return "数据不足"
    for lo, hi, label in VALUATION_BANDS:
        if lo <= pct < hi:
            return label
    return "高估"


def rolling_percentile(df, window_days, min_periods=60):
    df = df.sort_values("date").set_index("date")
    result = (
        df["value"]
        .rolling(f"{window_days}D", min_periods=min_periods)
        .apply(lambda x: np.mean(x < x[-1]) * 100, raw=True)
    )
    return result


# ── 底层 API 请求（不含缓存） ──

def _fetch_csindex_pe(param):
    df = ak.stock_zh_index_hist_csindex(
        param, start_date="20000101", end_date=_TODAY
    )
    col = "滚动市盈率"
    if df is None or df.empty or col not in df.columns:
        logger.warning("获取 %s PE 失败：数据为空或缺少 %s 列", param, col)
        return None
    out = df[["日期", col]].dropna().copy()
    out.columns = ["date", "value"]
    return out


def _fetch_csindex_price(param):
    df = ak.stock_zh_index_hist_csindex(
        param, start_date="20000101", end_date=_TODAY
    )
    col = "收盘"
    if df is None or df.empty or col not in df.columns:
        logger.warning("获取 %s 点位失败：数据为空或缺少 %s 列", param, col)
        return None
    out = df[["日期", col]].dropna().copy()
    out.columns = ["date", "value"]
    return out


def _fetch_market_pe(param):
    df = ak.stock_market_pe_lg(param)
    col = "平均市盈率"
    if df is None or df.empty or col not in df.columns:
        logger.warning("获取 %s 市场 PE 失败：数据为空或缺少 %s 列", param, col)
        return None
    out = df[["日期", col]].dropna().copy()
    out.columns = ["date", "value"]
    return out


def _fetch_market_pb(param):
    df = ak.stock_market_pb_lg(param)
    if df is None or df.empty or "市净率" not in df.columns:
        logger.warning("获取 %s 市场 PB 失败：数据为空或缺少市净率列", param)
        return None
    out = df[["日期", "市净率"]].dropna().copy()
    out.columns = ["date", "value"]
    return out


def _fetch_index_pe_lg(param):
    df = ak.stock_index_pe_lg(param)
    col = "滚动市盈率"
    if df is None or df.empty or col not in df.columns:
        logger.warning("获取 %s PE 失败：数据为空或缺少 %s 列", param, col)
        return None
    out = df[["日期", col]].dropna().copy()
    out.columns = ["date", "value"]
    return out


def _fetch_index_pb_lg(param):
    df = ak.stock_index_pb_lg(param)
    col = "市净率"
    if df is None or df.empty or col not in df.columns:
        logger.warning("获取 %s PB 失败：数据为空或缺少 %s 列", param, col)
        return None
    out = df[["日期", col]].dropna().copy()
    out.columns = ["date", "value"]
    return out


def _fetch_index_price_lg(param):
    df = ak.stock_index_pe_lg(param)
    col = "指数"
    if df is None or df.empty or col not in df.columns:
        logger.warning("获取 %s 点位失败：数据为空或缺少 %s 列", param, col)
        return None
    out = df[["日期", col]].dropna().copy()
    out.columns = ["date", "value"]
    return out


# ── 缓存感知的数据获取 ──

def _get_series(cfg, metric="pe"):
    name = cfg["name"]
    if metric == "pe":
        source = cfg["source"]
        param = cfg["param"]
    elif metric == "price":
        source = cfg["source"]
        param = cfg["param"]
    else:
        source = cfg.get("pb_source", cfg["source"])
        param = cfg.get("pb_param", cfg["param"])

    if source == "csindex":
        if metric == "pe":
            return get_or_update_series(name, "pe", source, lambda: _fetch_csindex_pe(param))
        if metric == "price":
            return get_or_update_series(name, "price", source, lambda: _fetch_csindex_price(param))

    if source == "market_pe":
        if metric == "pe":
            return get_or_update_series(name, "pe", source, lambda: _fetch_market_pe(param))
        if metric == "pb":
            return get_or_update_series(name, "pb", source, lambda: _fetch_market_pb(param))

    if source == "index_lg":
        if metric == "pe":
            return get_or_update_series(name, "pe", source, lambda: _fetch_index_pe_lg(param))
        if metric == "pb":
            return get_or_update_series(name, "pb", source, lambda: _fetch_index_pb_lg(param))
        if metric == "price":
            return get_or_update_series(name, "price", source, lambda: _fetch_index_price_lg(param))

    return pd.DataFrame(), False


# ── 公开接口 ──

def fetch_all():
    results = []
    for cfg in CONFIG:
        name = cfg["name"]
        try:
            df_pe, _ = _get_series(cfg, "pe")
            if df_pe.empty:
                logger.warning("获取 %s 估值失败：PE 数据为空", name)
                results.append({"name": name, "pe": None, "pct": None, "label": "获取失败"})
                continue
            pe = float(df_pe["value"].iloc[-1])
            pct = calc_percentile(df_pe["value"])
            r = {"name": name, "pe": pe, "pct": pct, "label": get_label(pct)}

            if cfg.get("pb"):
                df_pb, _ = _get_series(cfg, "pb")
                if not df_pb.empty:
                    pb = float(df_pb["value"].iloc[-1])
                    pb_pct = calc_percentile(df_pb["value"])
                    r["pb"] = pb
                    r["pb_pct"] = pb_pct
                    r["pb_label"] = get_label(pb_pct)
            results.append(r)
        except Exception:
            logger.warning("获取 %s 估值异常", name, exc_info=True)
            results.append({"name": name, "pe": None, "pct": None, "label": "获取失败"})
    return results


def fetch_series_all():
    results = []
    for cfg in CONFIG:
        name = cfg["name"]
        try:
            df_pe, _ = _get_series(cfg, "pe")
            r = {"name": name, "pe": df_pe if not df_pe.empty else None,
                 "pb": None, "price": None}
            if cfg.get("pb"):
                df_pb, _ = _get_series(cfg, "pb")
                r["pb"] = df_pb if not df_pb.empty else None
            df_price, _ = _get_series(cfg, "price")
            r["price"] = df_price if not df_price.empty else None
            results.append(r)
        except Exception:
            logger.warning("获取 %s 序列数据异常", name, exc_info=True)
            results.append({"name": name, "pe": None, "pb": None, "price": None})
    return results


def _fetch_bond_yield_10y(_=None):
    df = ak.bond_zh_us_rate()
    col = "中国国债收益率10年"
    if df is None or df.empty or col not in df.columns:
        logger.warning("获取十年期国债收益率失败")
        return None
    out = df[["日期", col]].dropna().copy()
    out.columns = ["date", "value"]
    return out


def _fetch_dividend_yield(_=None):
    indicator = ak.stock_zh_index_value_csindex(symbol="000922")
    if indicator is None or indicator.empty:
        logger.warning("获取中证红利指标数据失败，无法校准股息率")
        return None
    indicator.columns = ["date", "code", "full_name_cn", "short_name_cn",
                         "full_name_en", "short_name_en", "pe1", "pe2", "dp1", "dp2"]
    latest = indicator.iloc[0]
    dp1 = latest["dp1"]
    pe1 = latest["pe1"]
    if pd.isna(dp1) or pd.isna(pe1) or pe1 == 0:
        logger.warning("中证红利指标数据无效：dp1=%s pe1=%s", dp1, pe1)
        return None
    payout_ratio = dp1 * pe1 / 100

    pe_df, _ = get_or_update_series("中证红利", "pe", "csindex",
                                    lambda: _fetch_csindex_pe("000922"))
    if pe_df is None or pe_df.empty:
        logger.warning("获取中证红利历史PE失败，无法估算股息率")
        return None
    pe_df = pe_df.dropna()
    pe_df = pe_df[(pe_df["value"] > 0) & (pe_df["value"] < 1000)]
    if pe_df.empty:
        logger.warning("中证红利历史PE数据全部无效")
        return None

    out = pe_df[["date"]].copy()
    out["value"] = (payout_ratio / pe_df["value"]) * 100
    out = out.dropna()
    out = out.sort_values("date").reset_index(drop=True)
    return out


def fetch_bond_yield_10y():
    df, _ = get_or_update_series("中债", "10y", "bond", _fetch_bond_yield_10y)
    return df if not df.empty else None


def fetch_dividend_yield():
    df, _ = get_or_update_series("中证红利", "dividend_yield", "csindex_indicator",
                                 _fetch_dividend_yield)
    return df if not df.empty else None
