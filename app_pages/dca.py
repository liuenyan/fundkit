#!/usr/bin/env python3
"""
定投回测页面
"""

from datetime import datetime

import streamlit as st
import pandas as pd
from matplotlib.figure import Figure

from backend.charting import create_chart
from backend.dca_backtest import (
    BacktestError,
    fetch_dividend_data,
    fetch_fund_data,
    fetch_fund_name,
    generate_dca_dates,
    simulate_dca,
    calc_lumpsum,
)
from backend.strategy import FixedBuyStrategy, MovingAverageBuyStrategy, SellStrategy, TargetProfitSellStrategy, TrailingStopSellStrategy, ValueAveragingBuyStrategy
import db
from tools.stats import calc_annualized, max_drawdown

st.set_page_config(page_title="定投回测", page_icon="📊", layout="wide")


def make_charts(nav_df: pd.DataFrame, detail: pd.DataFrame, fund_code: str, fund_name: str) -> Figure:
    return create_chart(nav_df, detail, fund_code, fund_name)


with st.sidebar:
    st.header("⚙️ 回测参数")

    params = st.query_params
    default_code = params.get("fund", "163415")
    if "fund" in params:
        del params["fund"]
    fund_code = st.text_input("基金代码（6位）", default_code, key="fund_code_input", help="例：163415 = 兴全商业模式")

    buy_type = st.selectbox(
        "买入策略",
        ["定期定额", "价值平均", "指数均线"],
        format_func=lambda x: {"定期定额": "定期定额（每期固定金额）", "价值平均": "价值平均（每期增长固定市值）", "指数均线": "指数均线（低估多买高估少买）"}[x],
    )

    amount = 1000.0
    va_target = 1000.0
    va_max_multiple = 4.0
    va_min_amount = 10.0
    ma_period = 0

    if buy_type == "定期定额":
        amount = st.number_input("每期定投金额（元）", 1.0, 1e8, 1000.0, step=100.0)
    elif buy_type == "价值平均":
        va_target = st.number_input("每期市值增长目标（元）", 1.0, 1e8, 1000.0, step=100.0)
        c1, c2 = st.columns(2)
        with c1:
            va_max_multiple = st.number_input("最大投入倍数", 1.0, 100.0, 4.0, 0.5)
        with c2:
            va_min_amount = st.number_input("最低申购金额（元）", 1.0, 1000.0, 10.0, 5.0)
    else:
        amount = st.number_input("基础每期金额（元）", 1.0, 1e8, 1000.0, step=100.0)
        ma_period = st.selectbox("均线周期", [120, 250], index=1, help="低于均线多买，高于均线少买")

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

    try:
        nav_df = fetch_fund_data(fund_code, start_str, end_str)
    except BacktestError as e:
        st.error(str(e))
        st.stop()

    fund_name = fetch_fund_name(fund_code)
    dividend_df = fetch_dividend_data(fund_code)

    invest_dates = generate_dca_dates(nav_df, freq, start_str, end_str, day, weekday)
    if invest_dates.empty:
        st.error("未能生成有效的定投日期，请检查参数")
        st.stop()

    sell_strategy: SellStrategy | None = None
    if strategy == "策略A: 目标止盈":
        sell_strategy = TargetProfitSellStrategy(take_profit / 100)
    elif strategy == "策略B: 停投持有+移动止盈":
        sell_strategy = TrailingStopSellStrategy(stop_invest / 100, trailing_stop / 100)

    if buy_type == "指数均线":
        ma_start = (start_date - pd.Timedelta(days=ma_period * 2)).strftime("%Y-%m-%d")
        try:
            extra = db.fund_nav_history.load(fund_code, ma_start, start_str)
            if extra is not None and not extra.empty:
                extra["date"] = pd.to_datetime(extra["净值日期"])
                extra["unit_nav"] = pd.to_numeric(extra["单位净值"], errors="coerce")
                extra["acc_nav"] = pd.to_numeric(extra["累计净值"], errors="coerce")
                extra["daily_return"] = pd.to_numeric(extra["日增长率"], errors="coerce")
                ma_nav = pd.concat([extra, nav_df], ignore_index=True)
                ma_nav = ma_nav.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
            else:
                ma_nav = nav_df
        except Exception:
            ma_nav = nav_df
        buy_strategy = MovingAverageBuyStrategy(amount, ma_period, fee / 100, ma_nav)
    elif buy_type == "价值平均":
        buy_strategy = ValueAveragingBuyStrategy(va_target, va_max_multiple, va_min_amount, fee / 100)
    else:
        buy_strategy = FixedBuyStrategy(amount, fee / 100)

    try:
        detail, events, redeem_fee, final_val = simulate_dca(
            nav_df,
            invest_dates,
            buy_strategy,
            sell_strategy=sell_strategy,
            tp_cycle=tp_cycle,
            dividend_df=dividend_df,
        )
    except BacktestError as e:
        st.error(str(e))
        st.stop()

    total_invest = detail.iloc[-1]["total_invested"]
    portfolio_value = detail.iloc[-1]["total_value"]
    total_ret = (final_val - total_invest) / total_invest
    ann_ret = calc_annualized(total_ret, pd.Timestamp(start_str), pd.Timestamp(end_str))
    mdd = max_drawdown(detail["total_value"])

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

fig = make_charts(nav_df, detail, fund_code, fund_name)
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
    if sell_strategy is not None:
        event_dates = {e["date"] for e in events}
        display = detail[
            (detail["investment"] > 0) | (detail["dividend_units"] > 0) | detail["date"].isin(event_dates)
        ].copy()
    else:
        display = detail.copy()

    out = display.rename(
        columns={
            "date": "日期",
            "nav": "净值",
            "investment": "投入",
            "units_added": "申购份额",
            "dividend_units": "分红再投",
            "total_units": "累计份额",
            "market_value": "市值",
            "return_rate": "收益率(%)",
        }
    ).copy()
    out["日期"] = out["日期"].dt.strftime("%Y-%m-%d")
    out["收益率(%)"] = out["收益率(%)"] * 100
    out["分红再投"] = out["分红再投"].where(out["分红再投"] > 0).apply(
        lambda x: f"{x:.2f}" if pd.notna(x) else ""
    )
    cols = ["日期", "净值", "投入", "申购份额", "分红再投", "累计份额", "市值", "收益率(%)"]
    st.dataframe(out[cols], hide_index=True, use_container_width=True)

csv = detail.to_csv(index=False, encoding="utf-8-sig").encode()
st.download_button("📥 导出 CSV", data=csv, file_name=f"{fund_code}_dca_backtest.csv", mime="text/csv")
