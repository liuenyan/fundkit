"""
养老金基金 — Y份额基金筛选
数据源: 天天基金网 (via AKShare)
"""

import re

import pandas as pd
import akshare as ak
import streamlit as st

import db
from index_fund import SORT_OPTIONS


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
        scale_parts = []
        for stype in ["股票型基金", "混合型基金", "债券型基金", "QDII基金"]:
            sdf = ak.fund_scale_open_sina(symbol=stype)
            scale_parts.append(sdf)
        scale_all = pd.concat(scale_parts, ignore_index=True)
        scale_all = scale_all[["基金代码", "最新规模"]].drop_duplicates(subset="基金代码")
        scale_all = scale_all.rename(columns={"最新规模": "基金规模"})
        scale_all["基金规模"] = pd.to_numeric(scale_all["基金规模"], errors="coerce")
        result = result.merge(scale_all, on="基金代码", how="left")
    except Exception:
        result["基金规模"] = None

    return result


def filter_pension_funds(df, category):
    if not category or category == "全部":
        return df.copy()
    return df[df["养老金分类"] == category].copy()


def _fetch_fee_from_xq(code):
    try:
        df = ak.fund_individual_detail_info_xq(symbol=code)
        mgmt = cust = None
        for _, r in df.iterrows():
            cond = str(r.get("条件或名称", "")).strip()
            v = _parse_fee_val(r.get("费用"))
            if "管理费" in cond:
                mgmt = v
            if "托管费" in cond:
                cust = v
        return mgmt, cust
    except Exception:
        return None, None


def _parse_fee_val(v):
    if v is None:
        return None
    try:
        return float(str(v).replace("%", "").strip())
    except (ValueError, TypeError):
        return None


def enrich_pension_fees(result, progress_placeholder=None):
    result = result.copy()

    fee_raw = result["手续费"].astype(str).str.replace("%", "", regex=False)
    result["买入费率_天天"] = pd.to_numeric(fee_raw, errors="coerce")

    codes = result["基金代码"].tolist()
    cached = db.load_fund_fees(codes)

    mgmt_map = {}
    cust_map = {}
    uncached = []

    for c in codes:
        if c in cached:
            mgmt_map[c] = cached[c]["管理费"]
            cust_map[c] = cached[c]["托管费"]
        else:
            uncached.append(c)

    total = len(uncached)
    for i, c in enumerate(uncached):
        if progress_placeholder:
            progress_placeholder.markdown(f"正在获取费率信息… ({i+1}/{total})")
        mgmt, cust = _fetch_fee_from_xq(c)
        mgmt_map[c] = mgmt
        cust_map[c] = cust
        db.save_fund_fee(c, mgmt, cust)

    result["管理费"] = result["基金代码"].map(mgmt_map)
    result["托管费"] = result["基金代码"].map(cust_map)

    buy = result["买入费率_天天"].fillna(0)
    mgmt = result["管理费"]
    cust = result["托管费"]
    result["综合费率"] = ((buy + mgmt + cust).round(2)).where(
        mgmt.notna() & cust.notna(), pd.NA
    )
    return result


def sort_pension_funds(result, sort_by):
    sort_config = SORT_OPTIONS.get(sort_by) if sort_by else None
    if sort_config:
        col, asc = sort_config
        if col in result.columns:
            return result.sort_values(col, ascending=asc).reset_index(drop=True)
    result = result.sort_values("基金名称")
    return result.reset_index(drop=True)


__all__ = [
    "PENSION_CATEGORIES", "SORT_OPTIONS",
    "fetch_pension_funds", "filter_pension_funds",
    "enrich_pension_fees", "sort_pension_funds",
]
