#!/usr/bin/env python3
"""
指数估值 — 独立页面
"""

import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import streamlit as st

from cjk_font import setup_cjk_font
from backend.index_valuation import fetch_all as _fetch_valuation
from backend.index_valuation import fetch_series_all as _fetch_series
from backend.index_valuation import fetch_bond_yield_10y, fetch_dividend_yield
from backend.index_valuation import rolling_percentile
from backend.index_valuation import clear_cache

st.set_page_config(page_title="指数估值", page_icon="📈", layout="centered")

st.title("📈 指数估值百分位")
st.markdown("数据来源：中证指数 / 乐咕乐股（via AKShare）· 需联网")

col1, col2 = st.columns(2)
with col1:
    if st.button("🔄 刷新估值", type="primary", use_container_width=True):
        with st.spinner("正在获取指数估值数据..."):
            st.session_state["val_data"] = _fetch_valuation()
            st.session_state["val_series"] = _fetch_series()
with col2:
    if st.button("🗑️ 清除缓存并刷新", type="secondary", use_container_width=True):
        with st.spinner("正在清除缓存并重新获取..."):
            clear_cache()
            st.session_state["val_data"] = _fetch_valuation()
            st.session_state["val_series"] = _fetch_series()
            st.success("缓存已清除，数据已刷新")

if "val_data" not in st.session_state:
    st.info("👈 点击「刷新估值」获取最新数据")
    st.stop()

data = st.session_state["val_data"]
series = st.session_state.get("val_series", [])

for r in data:
    with st.container(border=True):
        has_pb = r.get("pb") is not None
        cols = st.columns([1, 1, 1, 1, 1, 1])
        emoji = {"低估": "🔵", "适中": "🟢", "高估": "🔴", "获取失败": "⚪", "数据不足": "⚪"}.get(r["label"], "⚪")

        cols[0].markdown(f"**{emoji} {r['name']}**")
        pe_str = f"{r['pe']:.2f}" if r["pe"] is not None else "—"
        cols[1].metric("PE", pe_str, delta_color="off")
        pct_str = f"{r['pct']:.1f}%" if r["pct"] is not None else "—"
        cols[2].metric("PE%", pct_str, delta_color="off")

        if has_pb:
            pb_str = f"{r['pb']:.2f}" if r["pb"] else "—"
            cols[3].metric("PB", pb_str, delta_color="off")
            pb_pct_str = f"{r['pb_pct']:.1f}%" if r["pb_pct"] else "—"
            cols[4].metric("PB%", pb_pct_str, delta_color="off")
        else:
            cols[3].metric("PB", "—", delta_color="off")
            cols[4].metric("PB%", "—", delta_color="off")

        cols[5].markdown(f"### {r['label']}")


WINDOWS_CAL_DAYS = {5: 1825, 10: 3650}


def _make_percentile_chart(df, label_name):
    setup_cjk_font()

    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.set_title(f"{label_name}", fontsize=13)
    ax.set_ylabel("百分位 (%)")
    ax.set_xlabel("日期")

    colors = {5: "#2196F3", 10: "#FF9800"}

    for year, cal_days in WINDOWS_CAL_DAYS.items():
        pct = rolling_percentile(df, cal_days)
        valid = pct.dropna()
        if len(valid) < 5:
            continue
        ax.plot(valid.index.values, valid.values, lw=1.2, label=f"{year}年滚动百分位", color=colors[year])

    ax.axhline(70, ls="--", lw=0.8, color="#f44336", alpha=0.5)
    ax.axhline(30, ls="--", lw=0.8, color="#4CAF50", alpha=0.5)
    ax.axhspan(70, 100, alpha=0.06, color="#f44336")
    ax.axhspan(30, 70, alpha=0.06, color="#FFC107")
    ax.axhspan(0, 30, alpha=0.06, color="#4CAF50")

    ax.set_ylim(-5, 105)

    # 叠加原始 PE/PB 数值
    ax2 = ax.twinx()
    value_label = label_name.split(" ")[-1] if " " in label_name else "Value"
    ax2.plot(df["date"], df["value"], lw=1.5, color="#555555", alpha=0.7, label=f"{value_label}")
    ax2.set_ylabel(value_label, color="#555555")
    ax2.tick_params(axis="y", labelcolor="#555555")

    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, fontsize=9, loc="upper left")

    ax.grid(True, alpha=0.2)
    fig.tight_layout()
    return fig


def _make_price_pe_chart(price_df, pe_df, name):
    setup_cjk_font()

    # 只显示 PE 数据覆盖的时间段，剔除指数发布前的虚拟数据
    pe_min = pe_df["date"].min()
    pe_max = pe_df["date"].max()
    price_df = price_df[(price_df["date"] >= pe_min) & (price_df["date"] <= pe_max)]

    fig, ax1 = plt.subplots(figsize=(10, 4.5))
    ax1.set_title(f"{name} 指数点位 & PE", fontsize=13)

    ax1.plot(price_df["date"], price_df["value"], lw=1.5, color="#2196F3", label="指数点位")
    ax1.set_ylabel("指数点位", color="#2196F3")
    ax1.tick_params(axis="y", labelcolor="#2196F3")
    ax1.grid(True, alpha=0.2)

    ax2 = ax1.twinx()
    ax2.plot(pe_df["date"], pe_df["value"], lw=1.5, color="#FF9800", label="PE")
    ax2.set_ylabel("PE", color="#FF9800")
    ax2.tick_params(axis="y", labelcolor="#FF9800")

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, fontsize=9, loc="upper left")

    fig.tight_layout()
    return fig


series_dict = {s["name"]: s for s in series if s is not None}

with st.expander("📊 历史百分位曲线", expanded=True):
    index_names = [r["name"] for r in data]
    if index_names:
        tabs = st.tabs(index_names)
        for idx, name in enumerate(index_names):
            with tabs[idx]:
                s = series_dict.get(name)
                if s is None or s["pe"] is None:
                    st.caption("无历史数据")
                    continue
                pe_df = s["pe"].copy()
                pe_df["date"] = pd.to_datetime(pe_df["date"])
                st.pyplot(_make_percentile_chart(pe_df, f"{name} PE"))

                if s.get("pb") is not None:
                    pb_df = s["pb"].copy()
                    pb_df["date"] = pd.to_datetime(pb_df["date"])
                    st.pyplot(_make_percentile_chart(pb_df, f"{name} PB"))

                if s.get("price") is not None and s.get("pe") is not None:
                    price_df = s["price"].copy()
                    price_df["date"] = pd.to_datetime(price_df["date"])
                    pe_chart_df = s["pe"].copy()
                    pe_chart_df["date"] = pd.to_datetime(pe_chart_df["date"])
                    st.pyplot(_make_price_pe_chart(price_df, pe_chart_df, name))


def _make_yield_compare_chart(bond_df, div_df):
    setup_cjk_font()
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax1 = plt.subplots(figsize=(10, 4.5))
    ax1.set_title("中证红利股息率 vs 十年期国债收益率", fontsize=13)

    ax1.plot(bond_df["date"], bond_df["value"], lw=1.5, color="#f44336", label="十年期国债收益率")
    ax1.set_ylabel("收益率 (%)", color="#f44336")
    ax1.tick_params(axis="y", labelcolor="#f44336")
    ax1.grid(True, alpha=0.2)

    ax2 = ax1.twinx()
    ax2.plot(div_df["date"], div_df["value"], lw=1.5, color="#4CAF50", label="中证红利股息率")
    ax2.set_ylabel("股息率 (%)", color="#4CAF50")
    ax2.tick_params(axis="y", labelcolor="#4CAF50")

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, fontsize=9, loc="upper left")

    fig.tight_layout()
    return fig


with st.expander("📊 中证红利股息率 vs 十年期国债收益率", expanded=False):
    bond_yield = fetch_bond_yield_10y()
    div_yield = fetch_dividend_yield()
    if bond_yield is None:
        st.caption("获取国债收益率失败")
    elif div_yield is None:
        st.caption("获取中证红利股息率失败")
    else:
        bond_df = bond_yield.copy()
        bond_df["date"] = pd.to_datetime(bond_df["date"])
        div_df = div_yield.copy()
        div_df["date"] = pd.to_datetime(div_df["date"])
        st.pyplot(_make_yield_compare_chart(bond_df, div_df))
        st.caption("股息率数据由中证红利PE（csindex）结合当前最新 股息率1×PE1 校准的 payout ratio 估算。")
