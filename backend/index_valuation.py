"""
指数估值百分位计算 + 历史百分位序列
数据源: 中证指数 (中证公司发布) 优先，乐咕乐股 (其他指数) 备用
"""

import logging
from datetime import datetime

import numpy as np
import pandas as pd
import akshare as ak

import db

logger = logging.getLogger(__name__)
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.WARNING,
)

_TODAY = datetime.now().strftime("%Y%m%d")

_FETCH_API = {
    ("csindex", "pe"):     (lambda p: ak.stock_zh_index_hist_csindex(p, start_date="20000101", end_date=_TODAY), "滚动市盈率"),
    ("csindex", "price"):  (lambda p: ak.stock_zh_index_hist_csindex(p, start_date="20000101", end_date=_TODAY), "收盘"),
    ("market_pe", "pe"):   (lambda p: ak.stock_market_pe_lg(p),          "平均市盈率"),
    ("market_pe", "pb"):   (lambda p: ak.stock_market_pb_lg(p),          "市净率"),
    ("index_lg", "pe"):    (lambda p: ak.stock_index_pe_lg(p),           "滚动市盈率"),
    ("index_lg", "pb"):    (lambda p: ak.stock_index_pb_lg(p),           "市净率"),
    ("index_lg", "price"): (lambda p: ak.stock_index_pe_lg(p),           "指数"),
}


def _fetch(source, metric, param):
    entry = _FETCH_API.get((source, metric))
    if entry is None:
        logger.warning("未知数据源/指标组合: %s/%s", source, metric)
        return None
    fetch_fn, col = entry
    df = fetch_fn(param)
    if df is None or df.empty or col not in df.columns:
        logger.warning("获取 %s %s 失败", param, metric)
        return None
    out = df[["日期", col]].dropna().copy()
    out.columns = ["date", "value"]
    return out

CONFIG = [
    {
        "name": "沪深300",
        "source": "csindex",
        "param": "000300",
        "pb": True,
        "pb_source": "index_lg",
        "pb_param": "沪深300",
    },
    {
        "name": "中证500",
        "source": "csindex",
        "param": "000905",
        "pb": True,
        "pb_source": "index_lg",
        "pb_param": "中证500",
    },
    {"name": "中证红利", "source": "csindex", "param": "000922"},
    {"name": "红利低波", "source": "csindex", "param": "H30269"},
    {"name": "CS消费50", "source": "csindex", "param": "931139"},
    {
        "name": "创业板50",
        "source": "index_lg",
        "param": "创业板50",
        "pb": True,
        "pb_source": "index_lg",
        "pb_param": "创业板50",
    },
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


# ── 缓存感知的数据获取 ──


def get_or_update_series(name, metric, source, fetch_fn):
    """
    返回 (DataFrame, 是否命中缓存)。

    如果缓存新鲜则直接返回缓存；否则调用 fetch_fn() 获取全量数据，
    新老合并后写入缓存再返回。
    """
    db.init_db()

    if db.is_series_fresh(name, metric):
        df = db.load_series(name, metric)
        return df, True

    try:
        df_raw = fetch_fn()
    except Exception:
        df_raw = None
    if df_raw is None or df_raw.empty:
        db.set_cache_meta(name, metric, source + ":failed")
        cached = db.load_series(name, metric)
        return cached, True

    db.upsert_series(name, metric, df_raw)
    db.set_cache_meta(name, metric, source)

    df = db.load_series(name, metric)
    return df, False


def clear_cache():
    db.clear_all()


def _get_series(cfg, metric="pe"):
    name = cfg["name"]
    if metric == "pb":
        source = cfg.get("pb_source", cfg["source"])
        param = cfg.get("pb_param", cfg["param"])
    else:
        source = cfg["source"]
        param = cfg["param"]
    return get_or_update_series(name, metric, source, lambda: _fetch(source, metric, param))


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
            r = {"name": name, "pe": df_pe if not df_pe.empty else None, "pb": None, "price": None}
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
    indicator.columns = [
        "date",
        "code",
        "full_name_cn",
        "short_name_cn",
        "full_name_en",
        "short_name_en",
        "pe1",
        "pe2",
        "dp1",
        "dp2",
    ]
    latest = indicator.iloc[0]
    dp1 = latest["dp1"]
    pe1 = latest["pe1"]
    if pd.isna(dp1) or pd.isna(pe1) or pe1 == 0:
        logger.warning("中证红利指标数据无效：dp1=%s pe1=%s", dp1, pe1)
        return None
    payout_ratio = dp1 * pe1 / 100

    pe_df, _ = get_or_update_series("中证红利", "pe", "csindex", lambda: _fetch("csindex", "pe", "000922"))
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
    df, _ = get_or_update_series("中证红利", "dividend_yield", "csindex_indicator", _fetch_dividend_yield)
    return df if not df.empty else None
