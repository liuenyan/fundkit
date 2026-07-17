"""
养老金基金 — Y份额基金筛选
数据源: fund_catalog + fund_nav + fund_fee + fund_scale (本地 DB, 单次 JOIN)
"""

import re
from typing import Any

import logging

import pandas as pd

import db
from . import fund_data

SORT_OPTIONS = fund_data.SORT_OPTIONS


def classify_pension_category(row: pd.Series | dict[str, Any]) -> str:
    name = str(row.get("基金名称", ""))
    fund_type = str(row.get("基金类型", ""))

    if fund_type == "指数型-股票":
        return "指数基金"

    if fund_type.startswith("FOF"):
        if re.search(r"20[3-6]\d", name):
            return "FOF-目标日期"
        if "稳健" in fund_type:
            return "FOF-目标风险-稳健"
        if "均衡" in fund_type:
            return "FOF-目标风险-均衡"
        if "进取" in fund_type:
            return "FOF-目标风险-积极"

    return "其他"


PENSION_CATEGORIES = [
    "全部",
    "指数基金",
    "FOF-目标日期",
    "FOF-目标风险-稳健",
    "FOF-目标风险-均衡",
    "FOF-目标风险-积极",
]


logger = logging.getLogger(__name__)


def fetch_pension_funds() -> pd.DataFrame:
    db.init_db()
    result = db.load_pension_funds()
    if result is None or result.empty:
        logger.warning("数据尚未采集，请运行：`uv run python collect_fund_data.py --nav`")
        return pd.DataFrame()
    result["养老金分类"] = result.apply(classify_pension_category, axis=1)
    return result


def filter_pension_funds(df: pd.DataFrame, category: str | None) -> pd.DataFrame:
    if not category or category == "全部":
        return df.copy()
    return df[df["养老金分类"] == category].copy()


def sort_pension_funds(result: pd.DataFrame, sort_by: str | None) -> pd.DataFrame:
    return fund_data.sort_result(result, sort_by)


__all__ = [
    "PENSION_CATEGORIES",
    "SORT_OPTIONS",
    "fetch_pension_funds",
    "filter_pension_funds",
    "sort_pension_funds",
]
