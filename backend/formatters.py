"""
格式化函数 — Streamlit 页面共用的数据渲染工具
"""

from typing import Any

import pandas as pd


def fmt_pct(v: Any) -> str:
    if pd.isna(v) or v == "":
        return "—"
    try:
        v = float(str(v).replace("%", ""))
        return f"{v:.2f}%"
    except (ValueError, TypeError):
        return str(v)


def fmt_nav(v: Any) -> str:
    if pd.isna(v) or v == "":
        return "—"
    try:
        return f"{float(v):.4f}"
    except (ValueError, TypeError):
        return str(v)


def fmt_scale(v: Any) -> str:
    if pd.isna(v) or v == "" or v is None:
        return "—"
    try:
        s = float(v)
        if s >= 1:
            return f"{s:.1f}亿"
        return f"{s * 10000:.0f}万"
    except (ValueError, TypeError):
        return str(v)


def fmt_total_fee(row: Any) -> str:
    buy = row.get("申购费")
    mgmt = row.get("管理费")
    cust = row.get("托管费")
    sales = row.get("销售服务费")
    total = row.get("综合费率")
    parts = []
    if pd.notna(total):
        parts.append(f"{total:.2f}%")
    else:
        parts.append("—")
    detail = []
    if pd.notna(buy):
        detail.append(f"申{fmt_pct(buy)}")
    if pd.notna(mgmt):
        detail.append(f"管{fmt_pct(mgmt)}")
    if pd.notna(cust):
        detail.append(f"托{fmt_pct(cust)}")
    if pd.notna(sales):
        detail.append(f"销{fmt_pct(sales)}")
    if detail:
        parts.append("(" + "+".join(detail) + ")")
    return " ".join(parts)
