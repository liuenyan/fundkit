#!/usr/bin/env python3
"""
全市场基金查询页面 — 多维度筛选
"""

import pandas as pd
import streamlit as st

from tools.formatters import fmt_nav, fmt_pct, fmt_scale, fmt_total_fee

from backend.fund_query import (
    FUND_CATEGORIES,
    SORT_OPTIONS,
    TOP_MANAGERS,
    load_all_funds,
    query_funds,
)

st.set_page_config(page_title="基金查询", page_icon="🔍", layout="centered")

st.title("🔍 基金查询")
st.markdown("从全市场基金中，按名称、公司、经理、类型等条件筛选")

CUSTOM_LABEL = "✏️ 自定义…"

all_funds = load_all_funds()
if all_funds.empty:
    st.error("基金数据尚未采集，请运行：`./venv/bin/python collect_fund_data.py`")
    st.stop()

# ── 筛选栏 ──

fcol1, fcol2, fcol3 = st.columns(3)
with fcol1:
    keyword = st.text_input("基金名称 / 代码 / 经理 / 公司", placeholder="输入关键词")
with fcol2:
    category = st.selectbox("基金类型", FUND_CATEGORIES)
with fcol3:
    manager_options = ["全部"] + TOP_MANAGERS + [CUSTOM_LABEL]
    manager_choice = st.selectbox("基金管理人", manager_options, index=0)

manager = None
if manager_choice == CUSTOM_LABEL:
    manager = st.text_input(
        "输入基金管理人名称",
        placeholder="例如：华夏基金、易方达基金",
        label_visibility="collapsed",
    )
elif manager_choice != "全部":
    manager = manager_choice

with st.expander("⚙️ 高级筛选"):
    afcol1, afcol2 = st.columns(2)
    with afcol1:
        fund_manager = st.text_input("基金经理", placeholder="输入基金经理姓名")
    with afcol2:
        sort_by = st.selectbox("排序方式", list(SORT_OPTIONS.keys()), index=0)

reset = st.button("🔄 重置筛选", type="secondary", use_container_width=True)
if reset:
    st.query_params.clear()
    st.rerun()

# ── 查询 + 展示 ──

result = query_funds(
    all_funds,
    keyword=keyword or None,
    category=category if category != "全部" else None,
    manager=manager or None,
    fund_manager=fund_manager or None,
    sort_by=sort_by,
)

if result.empty:
    st.warning("未找到匹配的基金，请尝试其他关键词")
    st.stop()

total = len(result)
st.success(f"共找到 {total} 只基金")

CARD_LIMIT = 50
show_limit = total > CARD_LIMIT

display = result[
    [
        "基金代码",
        "基金名称",
        "基金类型",
        "单位净值",
        "净值日期",
        "日增长率",
        "基金管理人",
        "基金经理",
        "综合费率",
        "申购费",
        "管理费",
        "托管费",
        "销售服务费",
        "基金规模",
        "成立日期",
        "跟踪标的",
        "跟踪方式",
    ]
].copy()

display["日增长率"] = display["日增长率"].apply(fmt_pct)
display["单位净值"] = display["单位净值"].apply(fmt_nav)
display["基金规模"] = display["基金规模"].apply(fmt_scale)
display["综合费率"] = display.apply(fmt_total_fee, axis=1)
display["申购费"] = display["申购费"].apply(lambda v: f"{v:.2f}%" if pd.notna(v) else "—")
display["管理费"] = display["管理费"].apply(fmt_pct)
display["托管费"] = display["托管费"].apply(fmt_pct)
display["销售服务费"] = display["销售服务费"].apply(fmt_pct)

display = display.rename(
    columns={
        "基金代码": "代码",
        "基金名称": "基金名称",
        "基金类型": "基金类型",
        "单位净值": "最新净值",
        "净值日期": "净值日期",
        "日增长率": "日涨跌",
        "基金管理人": "基金公司",
        "基金经理": "基金经理",
        "综合费率": "综合费率",
        "申购费": "申购费",
        "管理费": "管理费",
        "托管费": "托管费",
        "销售服务费": "销售服务费",
        "基金规模": "基金规模",
        "成立日期": "成立日期",
        "跟踪标的": "跟踪标的",
        "跟踪方式": "跟踪方式",
    }
)

if show_limit:
    st.info(f"显示前 {CARD_LIMIT} 只，完整列表请展开下方「📋 完整列表」")

for i, (_, row) in enumerate(display.head(CARD_LIMIT).iterrows()):
    with st.container(border=True):
        cols = st.columns([1.2, 2.5, 1, 0.8, 1.5, 0.8, 1])
        cols[0].markdown(f"**{row['代码']}**")
        cols[1].markdown(row["基金名称"])
        cols[2].markdown(f"净值: {row['最新净值']}")
        cols[3].markdown(f"涨跌: {row['日涨跌']}")
        cols[4].markdown(f"费率: {row['综合费率']}")
        cols[5].markdown(f"规模: {row['基金规模']}")
        if cols[6].button("📊 定投回测", key=f"dca_{row['代码']}_{i}", use_container_width=True):
            st.switch_page("app_pages/dca.py", query_params={"fund": row["代码"]})
        extra = []
        if row.get("基金公司"):
            extra.append(f"🏢 {row['基金公司']}")
        if row.get("基金经理"):
            extra.append(f"👤 {row['基金经理']}")
        if extra:
            st.caption(" | ".join(extra))

with st.expander("📋 完整列表", expanded=False):
    detail_cols = [
        "代码",
        "基金名称",
        "基金类型",
        "最新净值",
        "净值日期",
        "日涨跌",
        "基金公司",
        "基金经理",
        "综合费率",
        "申购费",
        "管理费",
        "托管费",
        "销售服务费",
        "基金规模",
        "成立日期",
        "跟踪标的",
        "跟踪方式",
    ]
    detail_df = display[[c for c in detail_cols if c in display.columns]].copy()
    st.dataframe(detail_df, hide_index=True, use_container_width=True)
