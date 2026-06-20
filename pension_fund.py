"""
养老金基金 — Y份额基金筛选
数据源: 天天基金网 (via AKShare)
"""

import re

import akshare as ak
import pandas as pd
import streamlit as st

import db
import fund_catalog
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

    names = fund_catalog.get_catalog()
    y_mask = names["基金简称"].str.contains(r"Y$|Y类", na=False, regex=True)
    y_funds = names[y_mask][["基金代码", "基金简称", "基金类型"]].copy()
    y_funds = y_funds.rename(columns={"基金简称": "基金名称"})

    # 开放基金净值（覆盖指数基金，不覆盖FOF）
    daily = ak.fund_open_fund_daily_em()
    nav_cols = [c for c in daily.columns if "单位净值" in c]
    nav_col = nav_cols[0] if nav_cols else None
    date_str = nav_col.split("-单位净值")[0] if nav_col else ""
    for sep in ("-", "/", "."):
        parts = date_str.split(sep)
        if len(parts) == 3:
            date_str = f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
            break

    daily_slim = pd.DataFrame({
        "基金代码": daily["基金代码"],
        "单位净值": pd.to_numeric(daily[nav_col], errors="coerce") if nav_col else None,
        "净值日期": date_str,
        "日增长率": daily.get("日增长率", ""),
        "手续费": pd.to_numeric(
            daily.get("手续费", pd.Series(dtype=str)).astype(str).str.replace("%", "", regex=False),
            errors="coerce",
        ),
    })

    result = y_funds.merge(daily_slim, on="基金代码", how="left")

    # FOF排名数据（覆盖FOF Y份额，含净值/区间收益率/手续费）
    fof_rank = ak.fund_open_fund_rank_em(symbol="FOF")
    fof_rank = fof_rank.rename(columns={
        "单位净值": "单位净值_fof",
        "日期": "净值日期_fof",
        "日增长率": "日增长率_fof",
        "手续费": "手续费_fof",
    })
    fof_cols = ["基金代码", "单位净值_fof", "净值日期_fof", "日增长率_fof", "手续费_fof",
                "累计净值", "近1周", "近1月", "近3月", "近6月",
                "近1年", "近2年", "近3年", "今年来", "成立来"]
    fof_cols = [c for c in fof_cols if c in fof_rank.columns]
    fof_slim = fof_rank[fof_cols].copy()

    # 归一化 FOF 手续费为数值
    if "手续费_fof" in fof_slim.columns:
        fof_slim["手续费_fof"] = pd.to_numeric(
            fof_slim["手续费_fof"].astype(str).str.replace("%", "", regex=False),
            errors="coerce",
        )

    result = result.merge(fof_slim, on="基金代码", how="left")

    # Coalesce: daily → fof
    result["单位净值"] = result["单位净值"].fillna(result["单位净值_fof"])
    result["净值日期"] = result["净值日期"].fillna(result["净值日期_fof"])
    result["日增长率"] = result["日增长率"].fillna(result["日增长率_fof"])
    result["手续费"] = result["手续费"].fillna(result["手续费_fof"])

    drop_cols = [c for c in result.columns if c.endswith("_fof")]
    result = result.drop(columns=drop_cols)

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
