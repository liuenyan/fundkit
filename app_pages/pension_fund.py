#!/usr/bin/env python3
"""
养老金选基页面 — Y份额基金筛选
"""

import pandas as pd
import streamlit as st

from backend.formatters import fmt_nav, fmt_pct, fmt_scale, fmt_total_fee

from backend.pension_fund import (
    PENSION_CATEGORIES,
    SORT_OPTIONS,
    fetch_pension_funds,
    filter_pension_funds,
    sort_pension_funds,
)

st.set_page_config(page_title="养老金选基", page_icon="🏦", layout="centered")

st.markdown(
    """
<style>
div[data-testid="column"] div[data-testid="stButton"] {
    display: flex;
    justify-content: center;
}
</style>
""",
    unsafe_allow_html=True,
)

st.title("🏦 养老金选基")
st.markdown("筛选个人养老金账户（Y份额）可投资的基金。费率与净值均从本地缓存读取，无需等待。")

CATEGORY_LABELS = {
    "指数基金": "📊",
    "FOF-目标日期": "📅",
    "FOF-目标风险-稳健": "🛡️",
    "FOF-目标风险-均衡": "⚖️",
    "FOF-目标风险-积极": "🚀",
}

col1, col2 = st.columns([2, 1])
with col1:
    category = st.selectbox("基金分类", options=PENSION_CATEGORIES, index=1)
with col2:
    sort_by = st.selectbox("排序方式", options=list(SORT_OPTIONS.keys()), index=0)

with st.spinner("获取养老金基金数据…"):
    all_funds = fetch_pension_funds()

cat = None if category == "全部" else category
result = filter_pension_funds(all_funds, cat)
result = sort_pension_funds(result, sort_by)

st.success(f"共 {len(result)} 只基金")

for i, (_, row) in enumerate(result.iterrows()):
    cat_label = row["养老金分类"]
    cat_icon = CATEGORY_LABELS.get(cat_label, "")
    with st.container(border=True):
        cols = st.columns([1.3, 2.2, 0.7, 0.7, 1.3, 0.7, 0.7])
        cols[0].markdown(f"**{row['基金代码']}**")
        cols[1].markdown(f"{row['基金名称']}")
        cols[2].markdown(f"{cat_icon} {cat_label.split('-')[-1]}")
        cols[3].markdown(f"净值: {fmt_nav(row['单位净值'])}")
        cols[4].markdown(f"费率: {fmt_total_fee(row)}")
        cols[5].markdown(f"规模: {fmt_scale(row.get('基金规模'))}")
        if cols[6].button("📊", key=f"dca_{row['基金代码']}_{i}", help="定投回测"):
            st.switch_page("app_pages/dca.py", query_params={"fund": row["基金代码"]})

with st.expander("📋 完整列表", expanded=False):
    detail_cols = [
        "基金代码",
        "基金名称",
        "养老金分类",
        "基金类型",
        "单位净值",
        "净值日期",
        "日增长率",
        "申购费",
        "销售服务费",
        "管理费",
        "托管费",
        "综合费率",
        "基金规模",
    ]
    detail_map = {
        "基金代码": "代码",
        "基金名称": "基金名称",
        "养老金分类": "分类",
        "基金类型": "基金类型",
        "单位净值": "最新净值",
        "净值日期": "净值日期",
        "日增长率": "日涨跌",
        "申购费": "申购费",
        "销售服务费": "销售服务费",
        "管理费": "管理费",
        "托管费": "托管费",
        "综合费率": "综合费率",
        "基金规模": "基金规模",
    }
    detail_df = result[[c for c in detail_cols if c in result.columns]].copy()
    detail_df["最新净值"] = detail_df["单位净值"].apply(fmt_nav)
    detail_df["日涨跌"] = detail_df["日增长率"].apply(fmt_pct)
    detail_df["申购费"] = detail_df.get("申购费", pd.Series(dtype=float)).apply(
        lambda v: f"{v:.2f}%" if pd.notna(v) else "—"
    )
    detail_df["管理费"] = detail_df["管理费"].apply(fmt_pct)
    detail_df["托管费"] = detail_df["托管费"].apply(fmt_pct)
    detail_df["基金规模"] = detail_df["基金规模"].apply(fmt_scale)
    detail_df["综合费率"] = detail_df.apply(fmt_total_fee, axis=1)
    display_cols = [
        "基金代码",
        "基金名称",
        "分类",
        "最新净值",
        "日涨跌",
        "综合费率",
        "申购费",
        "管理费",
        "托管费",
        "销售服务费",
        "基金规模",
    ]
    st.dataframe(
        detail_df[[c for c in display_cols if c in detail_df.columns]],
        hide_index=True,
        use_container_width=True,
    )
