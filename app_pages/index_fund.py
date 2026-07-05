#!/usr/bin/env python3
"""
指数选基页面 — 根据指数选择跟踪的指数基金
"""

import pandas as pd
import streamlit as st

from backend.formatters import fmt_nav, fmt_pct, fmt_scale, fmt_total_fee

from backend.index_fund import (
    COMMON_INDICES,
    SORT_OPTIONS,
    fetch_all_index_funds,
    filter_funds,
    search_funds_by_index,
    sort_result,
)

st.set_page_config(page_title="指数选基", page_icon="🎯", layout="centered")

st.title("🎯 指数选基")
st.markdown("选择一个指数，查看跟踪该指数的所有基金")

CUSTOM_LABEL = "✏️ 自定义搜索…"
index_choice = st.selectbox(
    "选择指数",
    options=[CUSTOM_LABEL] + COMMON_INDICES,
    index=None,
    placeholder="选择或搜索指数…",
)

if index_choice == CUSTOM_LABEL:
    custom = st.text_input(
        "输入指数名称",
        placeholder="例如：沪深300、中证白酒、科创50",
        label_visibility="collapsed",
    )
    index_name = custom.strip() if custom.strip() else None
elif index_choice:
    index_name = index_choice
else:
    index_name = None

if index_name:
    with st.spinner(f"正在查询跟踪「{index_name}」的基金…"):
        all_funds = fetch_all_index_funds()
        result = search_funds_by_index(all_funds, index_name)
        sort_by = "默认"

    if result.empty:
        st.warning(f"未找到跟踪「{index_name}」的基金，请尝试其他关键词")
        st.stop()

    st.success(f"共找到 {len(result)} 只跟踪「{index_name}」的基金")

    fcol1, fcol2, fcol3 = st.columns(3)
    with fcol1:
        fund_type = st.selectbox("基金类型", ["全部", "ETF", "ETF联接", "指数增强", "普通指数型"])
    with fcol2:
        share_class = st.selectbox("份额类别", ["全部", "A类", "C类", "E类", "Y类", "其他"])
    with fcol3:
        sort_by = st.selectbox("排序方式", options=list(SORT_OPTIONS.keys()), index=0)

    if fund_type != "全部":
        result = filter_funds(result, fund_type=fund_type)
    if share_class != "全部":
        result = filter_funds(result, share_class=share_class)
    result = sort_result(result, sort_by)

    display = result[
        [
            "基金代码",
            "基金名称",
            "单位净值",
            "日期",
            "日增长率",
            "跟踪标的",
            "跟踪方式",
            "综合费率",
            "申购费",
            "销售服务费",
            "管理费",
            "托管费",
            "基金规模",
        ]
    ].copy()

    display["日增长率"] = display["日增长率"].apply(fmt_pct)
    display["单位净值"] = display["单位净值"].apply(fmt_nav)
    display["基金规模"] = display["基金规模"].apply(fmt_scale)
    display["综合费率"] = display.apply(fmt_total_fee, axis=1)
    display["申购费"] = display["申购费"].apply(lambda v: f"{v:.2f}%" if pd.notna(v) else "—")
    display["销售服务费"] = display["销售服务费"].apply(fmt_pct)
    display["管理费"] = display["管理费"].apply(fmt_pct)
    display["托管费"] = display["托管费"].apply(fmt_pct)

    display = display.rename(
        columns={
            "基金代码": "代码",
            "基金名称": "基金名称",
            "单位净值": "最新净值",
            "日期": "净值日期",
            "日增长率": "日涨跌",
            "跟踪标的": "跟踪标的",
            "跟踪方式": "跟踪方式",
            "综合费率": "综合费率",
            "申购费": "申购费",
            "销售服务费": "销售服务费",
        }
    )

    for i, (_, row) in enumerate(display.iterrows()):
        with st.container(border=True):
            cols = st.columns([1.3, 2.5, 1, 0.8, 1.5, 0.8, 1])
            cols[0].markdown(f"**{row['代码']}**")
            cols[1].markdown(row["基金名称"])
            cols[2].markdown(f"净值: {row['最新净值']}")
            cols[3].markdown(f"涨跌: {row['日涨跌']}")
            cols[4].markdown(f"费率: {row['综合费率']}")
            cols[5].markdown(f"规模: {row['基金规模']}")
            if cols[6].button("📊 定投回测", key=f"dca_{row['代码']}_{i}", use_container_width=True):
                st.switch_page("app_pages/dca.py", query_params={"fund": row["代码"]})

    with st.expander("📋 完整列表", expanded=False):
        detail_cols = [
            "代码",
            "基金名称",
            "最新净值",
            "净值日期",
            "日涨跌",
            "跟踪标的",
            "综合费率",
            "申购费",
            "销售服务费",
            "管理费",
            "托管费",
            "跟踪方式",
            "基金规模",
        ]
        detail_df = display[[c for c in detail_cols if c in display.columns]].copy()
        st.dataframe(detail_df, hide_index=True, use_container_width=True)
else:
    st.info("👆 从下拉列表选择指数，或选「自定义搜索」输入关键词")
