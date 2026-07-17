#!/usr/bin/env python3
"""
全市场基金查询页面 — 多维度筛选
"""

import pandas as pd
import streamlit as st

from backend.formatters import fmt_nav, fmt_pct, fmt_scale, fmt_total_fee

from backend.fund_query import (
    FUND_CATEGORIES,
    SORT_OPTIONS,
    query_funds,
    fetch_top_managers as _fetch_top_managers,
    load_all_funds as _load_all_funds,
)


@st.cache_data(ttl=3600, show_spinner="获取全市场基金数据…")
def load_all_funds() -> pd.DataFrame:
    return _load_all_funds()


@st.cache_data(ttl=86400, show_spinner="获取基金管理人排名…")
def fetch_top_managers(n: int = 30) -> list[str]:
    return _fetch_top_managers(n)


st.set_page_config(page_title="基金查询", page_icon="🔍", layout="centered")

st.markdown(
    """
<style>
div[data-testid="column"] div[data-testid="stButton"] {
    display: grid;
    place-items: center;
}
</style>
""",
    unsafe_allow_html=True,
)

st.title("🔍 基金查询")
st.markdown("从全市场基金中，按名称、公司、经理、类型等条件筛选")

CUSTOM_LABEL = "✏️ 自定义…"

all_funds = load_all_funds()
if all_funds.empty:
    st.error("基金数据尚未采集，请运行：`uv run python collect_fund_data.py`")
    st.stop()

# ── 筛选栏 ──

fcol1, fcol2, fcol3 = st.columns(3)
with fcol1:
    keyword = st.text_input("基金名称 / 代码 / 经理 / 公司", placeholder="输入关键词")
with fcol2:
    category = st.selectbox("基金类型", FUND_CATEGORIES)
with fcol3:
    manager_options = ["全部"] + fetch_top_managers() + [CUSTOM_LABEL]
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
        "起购金额",
        "业绩比较基准",
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
        "起购金额": "起购金额",
        "业绩比较基准": "业绩比较基准",
    }
)

if show_limit:
    st.info(f"显示前 {CARD_LIMIT} 只，完整列表请展开下方「📋 完整列表」")

for i, (_, row) in enumerate(display.head(CARD_LIMIT).iterrows()):
    code = row["代码"]
    is_open = st.session_state.get("detail_fund") == code
    with st.container(border=True):
        cols = st.columns([1.0, 2.0, 0.8, 0.6, 1.0, 0.6, 0.8, 0.8])
        cols[0].markdown(f"**{code}**")
        cols[1].markdown(row["基金名称"])
        cols[2].markdown(f"净值: {row['最新净值']}")
        change = row["日涨跌"]
        if change == "—":
            colored_change = change
        elif change.startswith("-"):
            colored_change = f'<span style="color:#00a800">{change}</span>'
        else:
            colored_change = f'<span style="color:#cf0000">+{change}</span>'
        cols[3].markdown(f"涨跌: {colored_change}", unsafe_allow_html=True)
        cols[4].markdown(f"费率: {row['综合费率']}")
        cols[5].markdown(f"规模: {row['基金规模']}")
        toggle_label = "🔽" if is_open else "📋"
        if cols[6].button("📊", key=f"dca_{code}_{i}", help="定投回测"):
            st.switch_page("app_pages/dca.py", query_params={"fund": code})
        if cols[7].button(toggle_label, key=f"detail_{code}_{i}", help="查看基金详情"):
            if is_open:
                del st.session_state["detail_fund"]
            else:
                st.session_state["detail_fund"] = code
            st.rerun()
        extra = []
        if row.get("基金公司"):
            extra.append(f"🏢 {row['基金公司']}")
        if row.get("基金经理"):
            extra.append(f"👤 {row['基金经理']}")
        if extra:
            st.caption(" | ".join(extra))

    if is_open:
        with st.container(border=True):
            mc1, mc2, mc3 = st.columns(3)
            delta = row["日涨跌"]
            if delta not in ("—", "") and not delta.startswith("-"):
                delta = f"+{delta}"
            mc1.metric("最新净值", row["最新净值"], delta, delta_color="inverse")
            mc2.metric("综合费率", row["综合费率"].split()[0])
            mc3.metric("基金规模", row["基金规模"])

            st.markdown(
                f"**类型** {row['基金类型']}　"
                f"**公司** {row.get('基金公司', '—')}　"
                f"**经理** {row.get('基金经理', '—')}　"
                f"**成立** {row.get('成立日期', '—')}"
            )
            st.markdown(f"**跟踪标的** {row.get('跟踪标的', '—')}　**跟踪方式** {row.get('跟踪方式', '—')}")
            st.markdown(
                f"**申购费** {row['申购费']}　"
                f"**管理费** {row['管理费']}　"
                f"**托管费** {row['托管费']}　"
                f"**销售服务费** {row['销售服务费']}"
            )
            if pd.notna(row.get("起购金额")):
                st.markdown(f"**起购金额** {row['起购金额']}")
            if pd.notna(row.get("业绩比较基准")):
                st.markdown(f"**业绩比较基准** {row['业绩比较基准']}")

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
        "起购金额",
        "业绩比较基准",
    ]
    detail_df = display[[c for c in detail_cols if c in display.columns]].copy()
    st.dataframe(detail_df, hide_index=True, use_container_width=True)
