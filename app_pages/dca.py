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
from backend.index_fetcher import fetch_index_price, lookup_index
from backend.strategy import (
    FixedBuyStrategy,
    MovingAverageBuyStrategy,
    SellStrategy,
    TargetProfitSellStrategy,
    TrailingStopSellStrategy,
    ValueAveragingBuyStrategy,
)
import db
from backend.stats import (
    annualized_volatility,
    calc_annualized,
    calmar_ratio,
    max_drawdown,
    max_drawdown_duration,
    profit_loss_ratio,
    sharpe_ratio,
    win_rate,
)

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
        format_func=lambda x: {
            "定期定额": "定期定额（每期固定金额）",
            "价值平均": "价值平均（每期增长固定市值）",
            "指数均线": "指数均线（低估多买高估少买）",
        }[x],
    )

    amount = 1000.0
    va_target = 1000.0
    va_max_multiple = 4.0
    va_min_amount = 10.0
    ma_period = 0
    use_index_ma = False
    ma_mode = "default"
    ma_tiers_str = ""
    ma_mults_str = ""

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
        use_index_ma = st.checkbox("使用指数收盘价计算均线", True, help="用跟踪指数收盘价替代基金净值，无需缓冲期")
        ma_mode = st.selectbox(
            "偏离响应模式",
            list(MovingAverageBuyStrategy.MA_MODES),
            format_func=lambda x: {"default": "默认", "aggressive": "激进", "conservative": "保守"}[x],
        )
        with st.expander("自定义分档/倍数"):
            ma_tiers_str = st.text_input("偏差阈值（逗号分隔，如 -0.15,-0.08,-0.03,0.03）", "")
            ma_mults_str = st.text_input("买入倍数（逗号分隔，如 3.0,2.0,1.5,0.5,0.0）", "")

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
        if use_index_ma:
            profile = db.fund_profile.load([fund_code])
            tracking_target = profile.get(fund_code, {}).get("跟踪标的")
            index_info = lookup_index(tracking_target) if tracking_target else None
            if index_info:
                idx_code, src, mkt_prefix = index_info
                price_df = fetch_index_price(idx_code, src, mkt_prefix)
                if price_df is not None and not price_df.empty:
                    ma_nav = price_df.rename(columns={"value": "acc_nav"})
                    ma_nav["date"] = pd.to_datetime(ma_nav["date"])
                else:
                    st.info("指数价格获取失败，回退基金净值")
                    ma_nav = nav_df
            else:
                st.info(f"跟踪标的 '{tracking_target}' 未映射，回退基金净值")
                ma_nav = nav_df
        else:
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
        if ma_tiers_str.strip():
            ma_tiers = tuple(float(x) for x in ma_tiers_str.split(","))
        else:
            ma_tiers = MovingAverageBuyStrategy.MA_MODES[ma_mode][0]
        if ma_mults_str.strip():
            ma_mults = tuple(float(x) for x in ma_mults_str.split(","))
        else:
            ma_mults = MovingAverageBuyStrategy.MA_MODES[ma_mode][1]
        buy_strategy = MovingAverageBuyStrategy(amount, ma_period, fee / 100, ma_nav, ma_tiers, ma_mults)
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

vol = annualized_volatility(detail["total_value"], detail["total_invested"], detail["date"])
wr = win_rate(detail["return_rate"])
plr = profit_loss_ratio(detail["return_rate"])
dd_dur = max_drawdown_duration(detail["total_value"], detail["date"])

c1, c2, c3 = st.columns(3)
c1.metric("总收益率", f"{total_ret * 100:.2f}%")
c2.metric("年化收益率", f"{ann_ret * 100:.2f}%")
c3.metric("最大回撤", f"{mdd * 100:.2f}%", delta=f"{mdd * 100:.2f}%", delta_color="inverse")

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("年化波动率", f"{vol * 100:.2f}%")
c2.metric("Sharpe", f"{sharpe_ratio(ann_ret, vol):.2f}")
c3.metric("Calmar", f"{calmar_ratio(ann_ret, mdd):.2f}")
c4.metric("胜率", f"{wr * 100:.2f}%")
c5.metric("盈亏比", f"{plr:.2f}")
c6.metric("最大回撤持续期", f"{dd_dur}天")

fig = make_charts(nav_df, detail, fund_code, fund_name)
st.pyplot(fig)

if lumpsum:
    dd_ls = lumpsum["daily_detail"]
    ls_ret = lumpsum["return_rate"]
    ls_ann = calc_annualized(ls_ret, dd_ls["date"].iloc[0], dd_ls["date"].iloc[-1])
    ls_vol = annualized_volatility(dd_ls["total_value"], dd_ls["total_invested"], dd_ls["date"])
    ls_mdd = max_drawdown(dd_ls["total_value"])
    ls_sharpe = sharpe_ratio(ls_ann, ls_vol)
    ls_calmar = calmar_ratio(ls_ann, ls_mdd)
    ls_wr = win_rate(dd_ls["return_rate"])
    ls_plr = profit_loss_ratio(dd_ls["return_rate"])
    ls_dd_dur = max_drawdown_duration(dd_ls["total_value"], dd_ls["date"])

    st.subheader("💰 一次性投入对比")
    diff = total_ret - ls_ret
    winner = "定投胜 🏆" if diff > 0 else ("一次性投入胜 🏆" if diff < 0 else "持平")
    st.info(f"同等金额 **{total_invest:,.2f} 元** → **{winner}** (差值 {diff * 100:+.2f}%)")

    cols = st.columns(2)
    with cols[0]:
        st.caption("**定投**")
        st.metric("总收益率", f"{total_ret * 100:.2f}%")
        st.metric("年化收益率", f"{ann_ret * 100:.2f}%")
        st.metric("最大回撤", f"{mdd * 100:.2f}%")
        st.metric("年化波动率", f"{vol * 100:.2f}%")
        st.metric("Sharpe", f"{sharpe_ratio(ann_ret, vol):.2f}")
        st.metric("Calmar", f"{calmar_ratio(ann_ret, mdd):.2f}")
        st.metric("胜率", f"{wr * 100:.2f}%")
        st.metric("盈亏比", f"{plr:.2f}")
        st.metric("最大回撤持续期", f"{dd_dur}天")
    with cols[1]:
        st.caption("**一次性投入**")
        st.metric("总收益率", f"{ls_ret * 100:.2f}%")
        st.metric("年化收益率", f"{ls_ann * 100:.2f}%")
        st.metric("最大回撤", f"{ls_mdd * 100:.2f}%")
        st.metric("年化波动率", f"{ls_vol * 100:.2f}%")
        st.metric("Sharpe", f"{ls_sharpe:.2f}")
        st.metric("Calmar", f"{ls_calmar:.2f}")
        st.metric("胜率", f"{ls_wr * 100:.2f}%")
        st.metric("盈亏比", f"{ls_plr:.2f}")
        st.metric("最大回撤持续期", f"{ls_dd_dur}天")

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
            "deviation": "偏离",
            "multiplier": "倍数",
        }
    ).copy()
    out["日期"] = out["日期"].dt.strftime("%Y-%m-%d")
    out["收益率(%)"] = out["收益率(%)"] * 100
    out["分红再投"] = out["分红再投"].where(out["分红再投"] > 0).apply(lambda x: f"{x:.2f}" if pd.notna(x) else "")
    has_ma = "偏离" in out.columns and out["偏离"].notna().any()
    if has_ma:
        out["偏离"] = out["偏离"].where(out["偏离"].notna()).apply(lambda x: f"{x * 100:.2f}%" if pd.notna(x) else "")
        out["倍数"] = out["倍数"].where(out["倍数"].notna()).apply(lambda x: f"{x:.1f}x" if pd.notna(x) else "")
    cols = ["日期", "净值"]
    if has_ma:
        cols += ["偏离", "倍数"]
    cols += ["投入", "申购份额", "分红再投", "累计份额", "市值", "收益率(%)"]
    st.dataframe(out[cols], hide_index=True, use_container_width=True)

csv = detail.to_csv(index=False, encoding="utf-8-sig").encode()
st.download_button("📥 导出 CSV", data=csv, file_name=f"{fund_code}_dca_backtest.csv", mime="text/csv")
