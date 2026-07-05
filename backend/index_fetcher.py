"""
指数收盘价取数入口。

包装 get_or_update_series()，按 source 路由到对应 AKShare API。
缓存复用 index_series 表，metric="price"。
"""

import logging
from datetime import datetime

import akshare as ak
import pandas as pd

import db
from backend.index_valuation import get_or_update_series
from tools.build_index_name_map import normalize

logger = logging.getLogger(__name__)

_TODAY = datetime.now().strftime("%Y%m%d")

# ── 数据源后备链（Chain of Responsibility）──
# 每个数据源取不到时，按此链路由到下一个备用源，链尾为 None。
FALLBACK_MAP: dict[str, str | None] = {
    "csindex":  "daily_em",
    "daily_em": "sina_cn",
    "sina_cn":  None,
    "sina_hk":  None,
    "sina_us":  None,
}


def lookup_index(tracking_target: str) -> tuple[str, str, str | None] | None:
    """从跟踪标的名称查询 (index_code, source, market_prefix)，未映射则返回 None"""
    n = normalize(tracking_target)
    with db.engine.connect() as conn:
        row = conn.execute(
            db.text("SELECT index_code, source, market_prefix FROM index_name_map WHERE display_name=:n"),
            {"n": n},
        ).fetchone()
        if row:
            return row[0], row[1], row[2]
    return None


def fetch_index_price(index_code: str, source: str, market_prefix: str | None = None) -> pd.DataFrame | None:
    """获取指数历史收盘价，返回 (date, value) DataFrame，经 index_series 缓存。
    若首选 source 取不到，按 FALLBACK_MAP 自动链式重试。"""
    return get_or_update_series(
        index_code, "price", source,
        lambda: _fetch_chain(source, index_code, market_prefix),
    )[0]

def fetch_index_price_by_target(tracking_target: str) -> pd.DataFrame | None:
    """快捷入口：跟踪标的名称 → 指数价格"""
    info = lookup_index(tracking_target)
    if not info:
        return None
    idx_code, src, mkt_prefix = info
    return fetch_index_price(idx_code, src, mkt_prefix)


def _fetch_chain(source: str, code: str, market_prefix: str | None = None) -> pd.DataFrame | None:
    """按 FALLBACK_MAP 链式重试，任一数据源成功则返回。"""
    tried: list[str] = []
    while source is not None:
        result = _fetch_one(source, code, market_prefix)
        if result is not None:
            if tried:
                logger.info("链式取价成功: %s (失败 %s → 回退 %s)", source, " → ".join(tried), source)
            return result
        tried.append(source)
        source = FALLBACK_MAP[source]
    logger.warning("链式取价全部失败: %s", " → ".join(tried + ["None"]))
    return None


def _fetch_one(source: str, code: str, market_prefix: str | None = None) -> pd.DataFrame | None:
    """纯路由：按 source 派发到对应取价函数，不含任何兜底逻辑。"""
    if source == "csindex":
        return _fetch_csindex(code)
    elif source == "sina_hk":
        return _fetch_sina_hk(code)
    elif source == "sina_us":
        return _fetch_sina_us(code)
    elif source == "sina_cn":
        symbol = f"{market_prefix}{code}" if market_prefix else code
        return _fetch_sina_cn(symbol)
    elif source == "daily_em":
        symbol = f"{market_prefix}{code}" if market_prefix else code
        return _fetch_daily_em(symbol)
    logger.warning("未知数据源: %s", source)
    return None


def _fetch_csindex(code: str) -> pd.DataFrame | None:
    try:
        df = ak.stock_zh_index_hist_csindex(
            symbol=code, start_date="20000101", end_date=_TODAY
        )
        if df is None or df.empty or "收盘" not in df.columns:
            return None
        out = df[["日期", "收盘"]].dropna().copy()
        out.columns = ["date", "value"]
        return out
    except Exception as exc:
        logger.warning("csindex 取价失败 %s: %s", code, exc)
    return None


def _fetch_sina_cn(symbol: str) -> pd.DataFrame | None:
    """使用 Sina stock_zh_index_daily 获取 A 股指数收盘价。"""
    try:
        df = ak.stock_zh_index_daily(symbol=symbol)
        if df is None or df.empty or "close" not in df.columns:
            return None
        out = df[["date", "close"]].dropna().copy()
        out.columns = ["date", "value"]
        return out
    except Exception as exc:
        logger.warning("sina_cn 取价失败 %s: %s", symbol, exc)
        return None


def _fetch_sina_hk(symbol: str) -> pd.DataFrame | None:
    try:
        df = ak.stock_hk_index_daily_sina(symbol=symbol)
        if df is None or df.empty or "close" not in df.columns:
            return None
        out = df[["date", "close"]].dropna().copy()
        out.columns = ["date", "value"]
        return out
    except Exception as exc:
        logger.warning("sina_hk 取价失败 %s: %s", symbol, exc)
        return None


def _fetch_sina_us(symbol: str) -> pd.DataFrame | None:
    try:
        df = ak.index_us_stock_sina(symbol=symbol)
        if df is None or df.empty or "close" not in df.columns:
            return None
        out = df[["date", "close"]].dropna().copy()
        out.columns = ["date", "value"]
        return out
    except Exception as exc:
        logger.warning("sina_us 取价失败 %s: %s", symbol, exc)
        return None


def _fetch_daily_em(symbol: str) -> pd.DataFrame | None:
    try:
        df = ak.stock_zh_index_daily_em(
            symbol=symbol, start_date="20000101", end_date=_TODAY
        )
        if df is None or df.empty or "close" not in df.columns:
            return None
        out = df[["date", "close"]].dropna().copy()
        out.columns = ["date", "value"]
        return out
    except Exception as exc:
        logger.warning("daily_em 取价失败 %s: %s", symbol, exc)
        return None
