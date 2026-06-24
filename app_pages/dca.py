#!/usr/bin/env python3
"""
定投回测页面
"""

import io
import contextlib
from datetime import datetime
from collections.abc import Callable
from typing import Any

import streamlit as st
import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from tools.cjk_font import setup_cjk_font

from backend.dca_backtest import (
    fetch_dividend_data,
    fetch_fund_data as _fetch_fund_data,
    fetch_fund_name,
    generate_dca_dates,
    simulate_dca as _simulate_dca,
    calc_lumpsum,
    calc_annualized,
    max_drawdown,
)

st.set_page_config(page_title="定投回测", page_icon="📊", layout="wide")


def safe_call(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            return func(*args, **kwargs)
        except SystemExit:
            st.error(buf.getvalue())
            st.stop()


def fetch_fund_data(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
    return safe_call(_fetch_fund_data, *args, **kwargs)


def simulate_dca(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
    return safe_call(_simulate_dca, *args, **kwargs)


def make_charts(nav_df: pd.DataFrame, detail: pd.DataFrame, fund_code: str, fund_name: str, stop_profit_on: bool) -> None:
    setup_cjk_font()

    fig, axes = plt.subplots(2, 1, figsize=(12, 10), sharex=False)

    ax1 = axes[0]
    ax1.plot(nav_df["date"], nav_df["unit_nav"], color="steelblue", lw=1.2, alpha=0.9, label="单位净值")
    ax1.plot(nav_df["date"], nav_df["acc_nav"], color="steelblue", lw=0.8, ls="--", alpha=0.6, label="累计净值")
    if not detail.empty:
        avg = (detail["total_cost"] / detail["total_units"]).replace([np.inf, -np.inf], np.nan)
        ax1.plot(detail["date"], avg, color="crimson", lw=2, label="定投平均成本")
    ax1.set_title(f"{fund_name}（{fund_code}）净值走势与定投成本")
    ax1.legend(fontsize=10, loc="upper left")
    ax1.grid(True, alpha=0.25)
    ax1.set_ylabel("净值（元）")

    ax2 = axes[1]
    if not detail.empty:
        ret = detail["return_rate"] * 100
        ax2.plot(detail["date"], ret, color="forestgreen", lw=2, label="定投收益率")
        dd_col = "total_value" if stop_profit_on else "market_value"
        roll_max = detail[dd_col].expanding().max()
        dd = (detail[dd_col] - roll_max) / roll_max * 100
        ax2.fill_between(detail["date"].values, 0, dd.values, alpha=0.25, color="firebrick", label="回撤", step="pre")
    ax2.axhline(y=0, color="gray", ls="--", lw=0.6)
    ax2.set_title(f"{fund_name}（{fund_code}）定投收益率与回撤")
    ax2.legend(fontsize=10, loc="lower left")
    ax2.grid(True, alpha=0.25)
    ax2.set_ylabel("收益率（%）")
    ax2.set_xlabel("日期")

    plt.tight_layout()
    return fig


with st.sidebar:
    st.header("⚙️ 回测参数")

    params = st.query_params
    default_code = params.get("fund", "163415")
    if "fund" in params:
        del params["fund"]
    fund_code = st.text_input("基金代码（6位）", default_code, key="fund_code_input", help="例：163415 = 兴全商业模式")
    amount = st.number_input("每期定投金额（元）", 1.0, 1e8, 1000.0, step=100.0)

    freq = st.selectbox(
        "定投频率",
        ["monthly", "weekly", "biweekly", "daily"],
        format_func=lambda x: {"monthly": "每月", "weekly": "每周", "biweekly": "每两周", "daily": "每日"}[x],
    )
    day = st.slider("每月定投日 (1-28)", 1, 28, 10, disabled=freq != "monthly")
    weekday = st.selectbox(
        "每周定投日",
        [1, 2, 3, 4, 5],
        format_func=lambda x: {1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五"}[x],
        disabled=freq not in ("weekly", "biweekly"),
    )

    c1, c2 = st.columns(2)
    with c1:
        start_date = st.date_input("开始日期", datetime(2018, 1, 1))
    with c2:
        end_date = st.date_input("结束日期", datetime.today())

    st.subheader("费率")
    fee = st.number_input("申购费率 (%)", 0.0, 10.0, 0.15, 0.05, format="%.2f", help="默认 0.15%")

    st.subheader("止盈策略")

    strategy = st.selectbox(
        "选择策略",
        options=["不使用", "策略A: 目标止盈", "策略B: 停投持有+移动止盈"],
        label_visibility="collapsed",
    )

    take_profit = 0.0
    tp_cycle = False
    stop_invest = 0.0
    trailing_stop = 0.0

    if strategy == "策略A: 目标止盈":
        c1, c2 = st.columns(2)
        with c1:
            take_profit = st.number_input(
                "目标止盈收益率 (%)", 1, None, 20, 5, format="%d", help="收益达此百分比即卖出"
            )
        with c2:
            tp_cycle = st.checkbox("循环止盈模式", True, help="止盈后重新开始定投")
    elif strategy == "策略B: 停投持有+移动止盈":
        c1, c2 = st.columns(2)
        with c1:
            stop_invest = st.number_input(
                "停投触发收益率 (%)", 1, None, 20, 5, format="%d", help="收益达此百分比后停止定投，继续持有"
            )
        with c2:
            trailing_stop = st.number_input(
                "移动止盈回撤阈值 (%)", 1, 50, 8, 1, format="%d", help="从高点回撤此百分比即卖出"
            )
        tp_cycle = st.checkbox("循环止盈模式", True, help="止盈后重新开始定投")

    run_btn = st.button("🚀 开始回测", type="primary", use_container_width=True)


st.title("📊 定投回测")
st.markdown("数据源：天天基金网（via AKShare）· 需联网")

if not run_btn:
    st.info("👈 请在左侧填写参数，点击「开始回测」")
    st.stop()

with st.spinner("正在获取数据并计算…"):
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    nav_df = fetch_fund_data(fund_code, start_str, end_str)
    fund_name = fetch_fund_name(fund_code)
    dividend_df = fetch_dividend_data(fund_code)

    invest_dates = generate_dca_dates(nav_df, freq, start_str, end_str, day, weekday)
    if invest_dates.empty:
        st.error("未能生成有效的定投日期，请检查参数")
        st.stop()

    strategy_a = strategy == "策略A: 目标止盈"
    strategy_b = strategy == "策略B: 停投持有+移动止盈"
    stop_profit_on = strategy_a or strategy_b

    detail, events, redeem_fee, final_val = simulate_dca(
        nav_df,
        invest_dates,
        amount,
        fee / 100,
        take_profit=(take_profit / 100) if strategy_a else None,
        tp_cycle=tp_cycle,
        stop_invest=(stop_invest / 100) if strategy_b else None,
        trailing_stop=(trailing_stop / 100) if strategy_b else None,
        dividend_df=dividend_df,
    )

    if stop_profit_on:
        total_invest = detail.iloc[-1]["total_value"] - detail.iloc[-1]["profit"]
        portfolio_value = detail.iloc[-1]["total_value"]
    else:
        total_invest = detail.iloc[-1]["total_cost"]
        portfolio_value = detail.iloc[-1]["market_value"]

    total_ret = (final_val - total_invest) / total_invest
    ann_ret = calc_annualized(total_ret, pd.Timestamp(start_str), pd.Timestamp(end_str))
    value_col = "total_value" if stop_profit_on else "market_value"
    mdd = max_drawdown(detail[value_col])

    lumpsum = calc_lumpsum(nav_df, total_invest, start_str, end_str, fee / 100, dividend_df=dividend_df)

st.success(f"✅ 回测完成！共 {len(invest_dates)} 期定投，{events and len(events) or 0} 次止盈")

c1, c2, c3, c4 = st.columns(4)
c1.metric("总投入", f"{total_invest:,.2f} 元")
c2.metric("期末市值", f"{portfolio_value:,.2f} 元")
c3.metric("赎回费", f"{redeem_fee:,.2f} 元")
c4.metric("实际到账", f"{final_val:,.2f} 元")

c1, c2, c3 = st.columns(3)
c1.metric("总收益率", f"{total_ret * 100:.2f}%")
c2.metric("年化收益率", f"{ann_ret * 100:.2f}%")
c3.metric("最大回撤", f"{mdd * 100:.2f}%", delta=f"{mdd * 100:.2f}%", delta_color="inverse")

fig = make_charts(nav_df, detail, fund_code, fund_name, stop_profit_on)
st.pyplot(fig)

if lumpsum:
    st.subheader("💰 一次性投入对比")
    c1, c2, c3 = st.columns(3)
    c1.metric("一次性投入收益率", f"{lumpsum['return_rate'] * 100:.2f}%")
    c2.metric("定投收益率", f"{total_ret * 100:.2f}%")
    diff = total_ret - lumpsum["return_rate"]
    winner = "定投胜 🏆" if diff > 0 else ("一次性投入胜 🏆" if diff < 0 else "持平")
    c3.metric("差值", f"{diff * 100:+.2f}%")
    st.info(f"同等金额 **{total_invest:,.2f} 元** → **{winner}**")

if events:
    with st.expander(f"📋 止盈事件（共 {len(events)} 次）", expanded=True):
        ev_df = pd.DataFrame(events)
        ev_df["date"] = ev_df["date"].dt.strftime("%Y-%m-%d")
        ev_df["return_rate"] = ev_df["return_rate"] * 100
        ev_df = ev_df.rename(
            columns={
                "date": "日期",
                "nav": "净值",
                "return_rate": "收益率(%)",
                "round_cost": "轮次成本",
                "profit": "盈利",
                "redeem_fee": "赎回费",
                "net_proceeds": "净到账",
                "reason": "原因",
            }
        )
        st.dataframe(ev_df, hide_index=True, use_container_width=True)

with st.expander("📋 交易明细", expanded=False):
    if stop_profit_on:
        event_dates = {e["date"] for e in events}
        display = detail[(detail["investment"] > 0) | detail["date"].isin(event_dates)].copy()
    else:
        display = detail.copy()

    out = display.rename(
        columns={
            "date": "日期",
            "nav": "净值",
            "investment": "投入",
            "units_added": "新增份额",
            "total_units": "累计份额",
            "market_value": "市值",
            "return_rate": "收益率(%)",
        }
    ).copy()
    out["日期"] = out["日期"].dt.strftime("%Y-%m-%d")
    out["收益率(%)"] = out["收益率(%)"] * 100
    cols = ["日期", "净值", "投入", "新增份额", "累计份额", "市值", "收益率(%)"]
    st.dataframe(out[cols], hide_index=True, use_container_width=True)

csv = detail.to_csv(index=False, encoding="utf-8-sig").encode()
st.download_button("📥 导出 CSV", data=csv, file_name=f"{fund_code}_dca_backtest.csv", mime="text/csv")
