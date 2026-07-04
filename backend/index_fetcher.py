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
    """获取指数历史收盘价，返回 (date, value) DataFrame，经 index_series 缓存。"""
    return get_or_update_series(
        index_code, "price", source,
        lambda: _fetch(source, index_code, market_prefix),
    )[0]

def fetch_index_price_by_target(tracking_target: str) -> pd.DataFrame | None:
    """快捷入口：跟踪标的名称 → 指数价格"""
    info = lookup_index(tracking_target)
    if not info:
        return None
    idx_code, src, mkt_prefix = info
    return fetch_index_price(idx_code, src, mkt_prefix)


def _fetch(source: str, param: str, market_prefix: str | None = None) -> pd.DataFrame | None:
    if source == "csindex":
        return _fetch_csindex(param)
    elif source == "sina_hk":
        return _fetch_sina_hk(param)
    elif source == "sina_us":
        return _fetch_sina_us(param)
    elif source == "sina_cn":
        return _fetch_sina_cn(param, market_prefix)
    elif source == "daily_em":
        return _fetch_daily_em(f"{market_prefix}{param}" if market_prefix else param)
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
    # 399xxx 系列深证/国证指数：东财 → Sina 兜底
    if code.startswith("399"):
        em_symbol = f"sz{code}"
        result = _fetch_daily_em(em_symbol)
        if result is not None:
            return result
        logger.info("daily_em 失败，回退 sina_cn %s", code)
        return _fetch_sina_cn(code)
    return None


def _fetch_sina_cn(code: str, market_prefix: str | None = None) -> pd.DataFrame | None:
    """使用 Sina stock_zh_index_daily 获取 A 股指数收盘价。"""
    if market_prefix is None:
        with db.engine.connect() as conn:
            row = conn.execute(
                db.text("SELECT market_prefix FROM index_name_map WHERE index_code=:c"),
                {"c": code},
            ).fetchone()
            market_prefix = row[0] if row else None
    symbol = f"{market_prefix}{code}" if market_prefix else code
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
