"""
养老金基金 — Y份额基金筛选
数据源: 天天基金网 (via AKShare)
"""

import re

import akshare as ak
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
    "全部", "指数基金",
    "FOF-目标日期",
    "FOF-目标风险-稳健",
    "FOF-目标风险-均衡",
    "FOF-目标风险-积极",
]


@st.cache_data(ttl=3600, show_spinner="获取养老金基金数据…")
def fetch_pension_funds():
    db.init_db()

    names = ak.fund_name_em()
    y_mask = names["基金简称"].str.contains(r"Y$|Y类", na=False, regex=True)
    y_funds = names[y_mask].copy()

    daily = ak.fund_open_fund_daily_em()
    merged = y_funds.merge(daily, on="基金代码", how="left", suffixes=("", "_daily"))

    nav_cols = [c for c in daily.columns if "单位净值" in c]
    nav_col = nav_cols[0] if nav_cols else None
    date_str = nav_col.split("-单位净值")[0] if nav_col else ""
    for sep in ("-", "/", "."):
        parts = date_str.split(sep)
        if len(parts) == 3:
            date_str = f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
            break

    result_rows = []
    for _, r in merged.iterrows():
        nav = None
        if nav_col and r.get(nav_col) and str(r[nav_col]).strip():
            try:
                nav = float(r[nav_col])
            except (ValueError, TypeError):
                pass

        fee_raw = str(r.get("手续费", "")).replace("%", "")
        try:
            fee_val = float(fee_raw)
        except (ValueError, TypeError):
            fee_val = None

        result_rows.append({
            "基金代码": r["基金代码"],
            "基金名称": r.get("基金简称", r.get("基金简称_daily", "")),
            "基金类型": r["基金类型"],
            "单位净值": nav,
            "净值日期": date_str,
            "日增长率": r.get("日增长率", ""),
            "手续费": fee_val,
        })

    result = pd.DataFrame(result_rows)
    result["养老金分类"] = result.apply(classify_pension_category, axis=1)

    try:
        scale = fund_data.fetch_fund_scale()
        result = result.merge(scale, on="基金代码", how="left")
    except Exception:
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
    "fetch_pension_funds", "filter_pension_funds",
    "enrich_pension_fees", "sort_pension_funds",
]
