"""
养老金基金 — Y份额基金筛选
数据源: fund_catalog + fund_nav (本地 DB)
"""

import re

import pandas as pd
import streamlit as st

import db
import fund_data

SORT_OPTIONS = fund_data.SORT_OPTIONS


def classify_pension_category(row):
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


@st.cache_data(ttl=3600, show_spinner="获取养老金基金数据…")
def fetch_pension_funds():
    db.init_db()
    names = db.load_catalog()
    if names is None or names.empty:
        st.error("基金名录尚未采集，请运行：`./venv/bin/python collect_fund_data.py`")
        return pd.DataFrame()

    y_mask = names["基金简称"].str.contains(r"Y$|Y类", na=False, regex=True)
    y_funds = names[y_mask][["基金代码", "基金简称", "基金类型"]].copy()
    y_funds = y_funds.rename(columns={"基金简称": "基金名称"})

    nav = db.load_fund_nav()
    if nav is None or nav.empty:
        st.error("净值数据尚未采集，请运行：`./venv/bin/python collect_fund_data.py --nav`")
        return pd.DataFrame()

    result = y_funds.merge(
        nav[["基金代码", "单位净值", "累计净值", "日增长率", "日期"]],
        on="基金代码",
        how="left",
    )
    result = result.rename(columns={"日期": "净值日期"})
    result["养老金分类"] = result.apply(classify_pension_category, axis=1)
    result["基金规模"] = None
    return result


def filter_pension_funds(df, category):
    if not category or category == "全部":
        return df.copy()
    return df[df["养老金分类"] == category].copy()


def enrich_pension_fees(result, progress_placeholder=None):
    return fund_data.enrich_fee_scale(result, progress_placeholder=progress_placeholder)


def sort_pension_funds(result, sort_by):
    return fund_data.sort_result(result, sort_by)


__all__ = [
    "PENSION_CATEGORIES",
    "SORT_OPTIONS",
    "fetch_pension_funds",
    "filter_pension_funds",
    "enrich_pension_fees",
    "sort_pension_funds",
]
