#!/usr/bin/env python3
"""
指数估值 — 独立页面
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from backend.index_valuation import fetch_all as _fetch_valuation
from backend.index_valuation import fetch_series_all as _fetch_series
from backend.index_valuation import fetch_bond_yield_10y, fetch_dividend_yield
from backend.index_valuation import rolling_percentile
from backend.index_valuation import clear_cache

st.set_page_config(page_title="指数估值", page_icon="📈", layout="wide")

st.title("📈 指数估值百分位")
st.markdown("数据来源：中证指数 / 乐咕乐股（via AKShare）· 需联网")
st.caption("🔵 低估  🟢 适中  🔴 高估  ⚪ 数据不足")

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

        ma250_dev = r.get("ma250_dev")
        if ma250_dev is not None:
            pct = ma250_dev * 100
            color = "green" if pct <= -5 else "red" if pct >= 5 else "gray"
            cols[5].markdown(
                f"**MA250偏**<br><span style='color:{color};font-size:1.3rem'>{pct:+.1f}%</span>",
                unsafe_allow_html=True,
            )
        else:
            cols[5].metric("MA250偏", "—", delta_color="off")


WINDOWS_CAL_DAYS: dict[int, int] = {5: 1825, 10: 3650}


def _make_percentile_chart(df: pd.DataFrame, label_name: str) -> alt.LayerChart | alt.FacetChart:
    df = df.copy()

    for year, cal_days in WINDOWS_CAL_DAYS.items():
        pct = rolling_percentile(df, cal_days)
        df[f"pct_{year}y"] = pct.values

    id_cols = ["date", "value"]
    pct_long = df.melt(
        id_vars=id_cols,
        value_vars=["pct_5y", "pct_10y"],
        var_name="window",
        value_name="percentile",
    ).dropna(subset=["percentile"])
    pct_long["window"] = pct_long["window"].map({"pct_5y": "5年滚动百分位", "pct_10y": "10年滚动百分位"})

    value_label = label_name.split(" ")[-1] if " " in label_name else "Value"
    date_range = [df["date"].min(), df["date"].max()]

    ref30 = (
        alt.Chart(pd.DataFrame({"y": [30]}))
        .mark_rule(strokeDash=[3, 3], color="#4CAF50", opacity=0.5, size=0.8)
        .encode(y=alt.Y("y:Q", axis=None, scale=alt.Scale(domain=[-5, 105])))
    )
    ref70 = (
        alt.Chart(pd.DataFrame({"y": [70]}))
        .mark_rule(strokeDash=[3, 3], color="#f44336", opacity=0.5, size=0.8)
        .encode(y=alt.Y("y:Q", axis=None, scale=alt.Scale(domain=[-5, 105])))
    )

    pct_lines = (
        alt.Chart(pct_long)
        .mark_line(size=1.2)
        .encode(
            x=alt.X("date:T", title="日期"),
            y=alt.Y("percentile:Q", title="百分位 (%)", scale=alt.Scale(domain=[-5, 105])),
            color=alt.Color(
                "window:N",
                scale=alt.Scale(
                    domain=["5年滚动百分位", "10年滚动百分位"],
                    range=["#2196F3", "#FF9800"],
                ),
            ).legend(title="", orient="bottom"),
            tooltip=[
                alt.Tooltip("date:T", title="日期", format="%Y-%m-%d"),
                alt.Tooltip("percentile:Q", title="百分位", format=".1f"),
                alt.Tooltip("window:N", title="窗口"),
            ],
        )
    )

    raw_data = df.dropna(subset=["value"]).copy()
    raw_data["series"] = value_label
    raw_chart = (
        alt.Chart(raw_data)
        .mark_line(size=1.5)
        .encode(
            x=alt.X("date:T"),
            y=alt.Y("value:Q", axis=alt.Axis(titleColor="#E53935", title=value_label, orient="right")),
            color=alt.Color(
                "series:N",
                scale=alt.Scale(domain=[value_label], range=["#E53935"]),
                legend=alt.Legend(title="", orient="bottom"),
            ),
            tooltip=[
                alt.Tooltip("date:T", title="日期", format="%Y-%m-%d"),
                alt.Tooltip("value:Q", title=value_label, format=".2f"),
            ],
        )
    )

    zone_green = (
        alt.Chart(pd.DataFrame([{"x": date_range[0], "x2": date_range[1], "y0": 0, "y1": 30}]))
        .mark_rect(opacity=0.12, color="#4CAF50")
        .encode(
            x=alt.X("x:T", title=""),
            x2=alt.X2("x2:T"),
            y=alt.Y("y0:Q", axis=None, scale=alt.Scale(domain=[-5, 105])),
            y2=alt.Y2("y1:Q"),
        )
    )
    zone_yellow = (
        alt.Chart(pd.DataFrame([{"x": date_range[0], "x2": date_range[1], "y0": 30, "y1": 70}]))
        .mark_rect(opacity=0.12, color="#FFC107")
        .encode(
            x=alt.X("x:T", title=""),
            x2=alt.X2("x2:T"),
            y=alt.Y("y0:Q", axis=None, scale=alt.Scale(domain=[-5, 105])),
            y2=alt.Y2("y1:Q"),
        )
    )
    zone_red = (
        alt.Chart(pd.DataFrame([{"x": date_range[0], "x2": date_range[1], "y0": 70, "y1": 100}]))
        .mark_rect(opacity=0.12, color="#f44336")
        .encode(
            x=alt.X("x:T", title=""),
            x2=alt.X2("x2:T"),
            y=alt.Y("y0:Q", axis=None, scale=alt.Scale(domain=[-5, 105])),
            y2=alt.Y2("y1:Q"),
        )
    )

    combined = (
        alt.layer(pct_lines, raw_chart, zone_green, zone_yellow, zone_red, ref30, ref70)
        .resolve_scale(y="independent", color="independent")
        .properties(title=label_name)
        .configure_legend(direction="horizontal")
        .interactive()
    )

    return combined


def _make_price_pe_chart(price_df: pd.DataFrame, pe_df: pd.DataFrame, name: str) -> alt.LayerChart | alt.FacetChart:
    pe_min = pe_df["date"].min()
    pe_max = pe_df["date"].max()
    price_df = price_df[(price_df["date"] >= pe_min) & (price_df["date"] <= pe_max)]

    price_data = price_df.copy()
    price_data["series"] = "指数点位"
    price_chart = (
        alt.Chart(price_data)
        .mark_line(size=1.5)
        .encode(
            x=alt.X("date:T", title="日期"),
            y=alt.Y("value:Q", axis=alt.Axis(titleColor="#2196F3", title="指数点位")),
            color=alt.Color(
                "series:N",
                scale=alt.Scale(domain=["指数点位"], range=["#2196F3"]),
                legend=alt.Legend(title="", orient="bottom"),
            ),
            tooltip=[
                alt.Tooltip("date:T", title="日期", format="%Y-%m-%d"),
                alt.Tooltip("value:Q", title="指数点位", format=".2f"),
            ],
        )
    )

    pe_data = pe_df.copy()
    pe_data["series"] = "PE"
    pe_chart = (
        alt.Chart(pe_data)
        .mark_line(size=1.5)
        .encode(
            x=alt.X("date:T"),
            y=alt.Y("value:Q", axis=alt.Axis(titleColor="#FF9800", title="PE", orient="right")),
            color=alt.Color(
                "series:N",
                scale=alt.Scale(domain=["PE"], range=["#FF9800"]),
                legend=alt.Legend(title="", orient="bottom"),
            ),
            tooltip=[
                alt.Tooltip("date:T", title="日期", format="%Y-%m-%d"),
                alt.Tooltip("value:Q", title="PE", format=".2f"),
            ],
        )
    )

    combined = (
        alt.layer(price_chart, pe_chart)
        .resolve_scale(y="independent", color="independent")
        .properties(title=f"{name} 指数点位 & PE")
        .configure_legend(direction="horizontal")
        .interactive()
    )

    return combined


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
                st.altair_chart(_make_percentile_chart(pe_df, f"{name} PE"), use_container_width=True)

                if s.get("pb") is not None:
                    pb_df = s["pb"].copy()
                    pb_df["date"] = pd.to_datetime(pb_df["date"])
                    st.altair_chart(_make_percentile_chart(pb_df, f"{name} PB"), use_container_width=True)

                if s.get("price") is not None and s.get("pe") is not None:
                    price_df = s["price"].copy()
                    price_df["date"] = pd.to_datetime(price_df["date"])
                    pe_chart_df = s["pe"].copy()
                    pe_chart_df["date"] = pd.to_datetime(pe_chart_df["date"])
                    st.altair_chart(_make_price_pe_chart(price_df, pe_chart_df, name), use_container_width=True)


def _make_yield_compare_chart(bond_df: pd.DataFrame, div_df: pd.DataFrame) -> alt.LayerChart | alt.FacetChart:
    bond_data = bond_df.copy()
    bond_data["series"] = "十年期国债收益率"
    bond_chart = (
        alt.Chart(bond_data)
        .mark_line(size=1.5)
        .encode(
            x=alt.X("date:T", title="日期"),
            y=alt.Y("value:Q", axis=alt.Axis(titleColor="#f44336", title="收益率 (%)")),
            color=alt.Color(
                "series:N",
                scale=alt.Scale(domain=["十年期国债收益率"], range=["#f44336"]),
                legend=alt.Legend(title="", orient="bottom"),
            ),
            tooltip=[
                alt.Tooltip("date:T", title="日期", format="%Y-%m-%d"),
                alt.Tooltip("value:Q", title="收益率", format=".2f"),
            ],
        )
    )

    div_data = div_df.copy()
    div_data["series"] = "中证红利股息率"
    div_chart = (
        alt.Chart(div_data)
        .mark_line(size=1.5)
        .encode(
            x=alt.X("date:T"),
            y=alt.Y("value:Q", axis=alt.Axis(titleColor="#4CAF50", title="股息率 (%)", orient="right")),
            color=alt.Color(
                "series:N",
                scale=alt.Scale(domain=["中证红利股息率"], range=["#4CAF50"]),
                legend=alt.Legend(title="", orient="bottom"),
            ),
            tooltip=[
                alt.Tooltip("date:T", title="日期", format="%Y-%m-%d"),
                alt.Tooltip("value:Q", title="股息率", format=".2f"),
            ],
        )
    )

    combined = (
        alt.layer(bond_chart, div_chart)
        .resolve_scale(y="independent", color="independent")
        .properties(title="中证红利股息率 vs 十年期国债收益率")
        .configure_legend(direction="horizontal")
        .interactive()
    )

    return combined


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
        st.altair_chart(_make_yield_compare_chart(bond_df, div_df), use_container_width=True)
        st.caption("股息率数据由中证红利PE（csindex）结合当前最新 股息率1×PE1 校准的 payout ratio 估算。")
