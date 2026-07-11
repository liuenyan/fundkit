"""
指数收盘价取数入口。

包装 get_or_update_series()，按 source 路由到对应 AKShare API。
缓存复用 index_series 表，metric="price"。
"""

import logging
from collections.abc import Callable
from datetime import datetime

import akshare as ak
import pandas as pd
import requests

import db
from backend.index_valuation import get_or_update_series
from tools.build_index_name_map import normalize

logger = logging.getLogger(__name__)

_TODAY = datetime.now().strftime("%Y%m%d")

# ── 数据源后备链（Chain of Responsibility）──
# 每个数据源取不到时，按此链路由到下一个备用源，链尾为 None。
FALLBACK_MAP: dict[str, str | None] = {
    "csindex": "daily_em",
    "daily_em": "sina_cn",
    "sina_cn": None,
    "sina_hk": None,
    "sina_us": None,
    "hsi": "sina_hk",
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
        index_code,
        "price",
        source,
        lambda: _fetch_chain(source, index_code, market_prefix),
    )[0]


def fetch_index_price_by_target(tracking_target: str) -> pd.DataFrame | None:
    """快捷入口：跟踪标的名称 → 指数价格"""
    info = lookup_index(tracking_target)
    if not info:
        return None
    idx_code, src, mkt_prefix = info
    return fetch_index_price(idx_code, src, mkt_prefix)


def _fetch_chain(source: str | None, code: str, market_prefix: str | None = None) -> pd.DataFrame | None:
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
    elif source == "hsi":
        return _fetch_hsi(code)
    elif source == "sina_cn":
        symbol = f"{market_prefix}{code}" if market_prefix else code
        return _fetch_sina_cn(symbol)
    elif source == "daily_em":
        symbol = f"{market_prefix}{code}" if market_prefix else code
        return _fetch_daily_em(symbol)
    logger.warning("未知数据源: %s", source)
    return None


def _fetch_with(
    api_func: Callable[..., pd.DataFrame],
    *,
    date_col: str = "date",
    close_col: str = "close",
    **fixed_kwargs: object,
) -> Callable[[str], pd.DataFrame | None]:
    """返回一个 (symbol: str) -> pd.DataFrame | None 签名的取价函数。"""

    def fetcher(symbol: str) -> pd.DataFrame | None:
        try:
            df = api_func(symbol=symbol, **fixed_kwargs)
            if df is None or df.empty or close_col not in df.columns:
                return None
            out = df[[date_col, close_col]].dropna().copy()
            out.columns = ["date", "value"]
            return out
        except Exception as exc:
            logger.warning("取价失败 %s: %s", symbol, exc)
        return None

    return fetcher


_fetch_csindex = _fetch_with(
    ak.stock_zh_index_hist_csindex,
    date_col="日期",
    close_col="收盘",
    start_date="20000101",
    end_date=_TODAY,
)
_fetch_daily_em = _fetch_with(
    ak.stock_zh_index_daily_em,
    start_date="20000101",
    end_date=_TODAY,
)
_fetch_sina_cn = _fetch_with(ak.stock_zh_index_daily)
_fetch_sina_hk = _fetch_with(ak.stock_hk_index_daily_sina)
_fetch_sina_us = _fetch_with(ak.index_us_stock_sina)


def _fetch_hsi(symbol: str) -> pd.DataFrame | None:
    """从恒生指数公司官网 chart-rebased.json 获取指数历史收盘价。
    symbol 为恒生指数代码（如 HSI, HSCEI, HSTECH, HSSCNE 等）。
    网站 API 使用小写代码路径（hsi, hscei, hstech, hsscne）。
    返回的 indexLevels-Xy 均为基准化值（period start=100），
    通过 previousClose 换算为实际收盘价。
    """
    try:
        code = symbol.lower()
        url = f"https://www.hsi.com.hk/data/eng/index-series/{code}/chart-rebased.json"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        series = data["indexSeriesList"][0]
        entry = series["indexList"][0]

        prev_close = entry.get("previousClose")
        if not prev_close:
            return None
        actual_close = float(prev_close)

        # 取数据最长的 period（5y > 3y > 1y > 6m > ytd > 3m > 1m）
        best_key = None
        for suffix in ["-5y", "-3y", "-1y", "-6m", "-ytd", "-3m", "-1m"]:
            key = f"indexLevels{suffix}"
            if key in entry and len(entry[key]) > 0:
                best_key = key
                break
        if best_key is None:
            return None

        raw = entry[best_key]
        last_rebased = raw[-1][1]
        factor = actual_close / last_rebased

        records = []
        for ts_ms, rebased in raw:
            dt = datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")
            records.append({"date": dt, "value": round(rebased * factor, 2)})

        df = pd.DataFrame(records)
        return df
    except Exception as exc:
        logger.warning("HSI API 取价失败 %s: %s", symbol, exc)
        return None
