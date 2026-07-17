#!/usr/bin/env python3
"""
中国开放式基金定投回测工具 — CLI 入口

依赖 backend.dca_engine 执行模拟，本模块负责参数解析、终端输出、图表保存。
"""

import argparse
import os
import sys
from datetime import datetime
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

import db
from backend.charting import create_chart
from backend.dca_engine import (
    BacktestError,
    calc_lumpsum,
    fetch_dividend_data,
    fetch_fund_data,
    fetch_fund_name,
    generate_dca_dates,
    load_ma_buffer,
    simulate_dca,
)
from backend.index_fetcher import fetch_index_price, lookup_index
from backend.logger import setup_logging
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
from backend.strategy import (
    FixedBuyStrategy,
    MovingAverageBuyStrategy,
    SellStrategy,
    TargetProfitSellStrategy,
    TrailingStopSellStrategy,
    ValueAveragingBuyStrategy,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="中国开放式基金定投回测工具")
    p.add_argument("--fund", required=True, help="基金代码（6位）")
    p.add_argument("--amount", type=float, default=0, help="每期定投金额（--value-avg 启用时忽略）")
    p.add_argument(
        "--freq",
        choices=["daily", "weekly", "biweekly", "monthly"],
        default="monthly",
        help="定投频率",
    )
    p.add_argument("--day", type=int, default=10, help="每月定投日 (1-28，仅 monthly 有效)")
    p.add_argument(
        "--weekday",
        type=int,
        default=1,
        choices=range(1, 6),
        help="每周定投日 (1=周一..5=周五，仅 weekly/biweekly 有效)",
    )
    p.add_argument("--start", required=True, help="开始日期 YYYY-MM-DD")
    p.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD（默认今天）")
    p.add_argument(
        "--fee",
        type=float,
        default=0.0015,
        help="申购费率 (默认 0.0015 = 0.15%%)",
    )
    p.add_argument("--output", default=None, help="CSV 导出路径")
    p.add_argument("--chart", default="./charts", help="图表输出目录")

    p.add_argument(
        "--take-profit", type=float, default=0, help="【策略A】目标止盈收益率 (如 0.20 表示收益达 20%% 即卖出)"
    )
    p.add_argument("--tp-cycle", action="store_true", help="【策略A】循环止盈模式（止盈后重新开始定投）")
    p.add_argument(
        "--stop-invest",
        type=float,
        default=0,
        help="【策略B】停投触发收益率 (如 0.20 表示收益达 20%% 即停投，配合 --trailing-stop 使用)",
    )
    p.add_argument(
        "--trailing-stop", type=float, default=0, help="【策略B】移动止盈回撤阈值 (如 0.08 表示从高点回撤 8%% 即卖出)"
    )

    p.add_argument(
        "--value-avg", type=float, default=0, help="【价值平均】每期市值增长目标 (如 1000 表示每月目标增长 1000 元市值)"
    )
    p.add_argument("--va-max-multiple", type=float, default=4.0, help="【价值平均】每期最大投入倍数 (默认 4 倍)")
    p.add_argument("--va-min-amount", type=float, default=10.0, help="【价值平均】最低申购金额 (默认 10 元)")

    p.add_argument(
        "--ma-period", type=int, default=0, help="【均线策略】均线周期 (如 250，>0 启用均线策略，忽略 --value-avg)"
    )
    p.add_argument("--index-ma", action="store_true", help="【均线策略】使用跟踪指数收盘价替代基金净值计算均线")
    p.add_argument(
        "--ma-mode",
        default="default",
        choices=list(MovingAverageBuyStrategy.MA_MODES),
        help="【均线策略】偏离响应模式 (default / aggressive / conservative)",
    )
    p.add_argument("--ma-tiers", default=None, help="【均线策略】自定义偏差阈值，逗号分隔 (如 -0.15,-0.08,-0.03,0.03)")
    p.add_argument(
        "--ma-multipliers", default=None, help="【均线策略】自定义买入倍数，逗号分隔 (如 3.0,2.0,1.5,0.5,0.0)"
    )
    return p.parse_args()


def plot_results(
    nav_df: pd.DataFrame,
    detail: pd.DataFrame,
    fund_code: str,
    fund_name: str,
    start_date: str,
    end_date: str,
    chart_dir: str,
) -> None:
    """生成分析图表并保存到文件"""
    os.makedirs(chart_dir, exist_ok=True)

    assert not nav_df.empty, "nav_df 为空"
    assert "unit_nav" in nav_df.columns
    assert "acc_nav" in nav_df.columns
    if not detail.empty:
        assert "total_cost" in detail.columns
        assert "total_units" in detail.columns

    fig = create_chart(nav_df, detail, fund_code, fund_name)
    path = os.path.join(chart_dir, f"{fund_code}_dca_backtest.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"图表已保存: {path}")


def _calc_extra_metrics(
    total_value: pd.Series,
    return_rate: pd.Series,
    ann_ret: float,
    total_invested: pd.Series | None = None,
    dates: pd.Series | None = None,
) -> dict[str, float]:
    vol = annualized_volatility(total_value, total_invested, dates)
    mdd_s = max_drawdown(total_value)
    return {
        "vol": vol,
        "sharpe": sharpe_ratio(ann_ret, vol),
        "calmar": calmar_ratio(ann_ret, mdd_s),
        "win_rate": win_rate(return_rate),
        "pl_ratio": profit_loss_ratio(return_rate),
        "dd_dur": max_drawdown_duration(total_value, dates),
    }


def print_summary(
    fund_name: str,
    fund_code: str,
    start: str,
    end: str,
    freq: str,
    amount: float,
    fee: float,
    detail: pd.DataFrame,
    redeem_fee: float,
    final_val: float,
    total_ret: float,
    ann_ret: float,
    mdd: float,
    lumpsum: dict[str, Any] | None,
) -> None:
    total_invest = detail.iloc[-1]["total_invested"]
    portfolio_value = detail.iloc[-1]["total_value"]
    em = _calc_extra_metrics(
        detail["total_value"], detail["return_rate"], ann_ret, detail["total_invested"], detail["date"]
    )
    sep = "=" * 52
    print(f"""
{sep}
定投回测结果
{sep}
基金: {fund_name}（{fund_code}）
回测期间: {start}  →  {end}
定投频率: {freq:<8}  每期: {amount:>8,.2f} 元
申购费率: {fee * 100:.2f}%

{"─" * 52}
总投入:        {total_invest:>12,.2f} 元
期末市值:      {portfolio_value:>12,.2f} 元
赎回费:        {redeem_fee:>12,.2f} 元
实际到账:      {final_val:>12,.2f} 元
总收益率:      {total_ret * 100:>12.2f}%
年化收益率:    {ann_ret * 100:>12.2f}%
最大回撤:      {mdd * 100:>12.2f}%
年化波动率:    {em["vol"] * 100:>12.2f}%
Sharpe 比率:   {em["sharpe"]:>12.2f}
Calmar 比率:   {em["calmar"]:>12.2f}
胜率:          {em["win_rate"] * 100:>12.2f}%
盈亏比:        {em["pl_ratio"]:>12.2f}
最大回撤持续期: {em["dd_dur"]:>8} 天

{"─" * 52}
一次性投入对比（同等金额 {total_invest:,.2f} 元）:
""")
    if lumpsum:
        dd = lumpsum["daily_detail"]
        lumpsum_ret = lumpsum["return_rate"]
        lumpsum_ann = calc_annualized(lumpsum_ret, dd["date"].iloc[0], dd["date"].iloc[-1])
        ls_em = _calc_extra_metrics(dd["total_value"], dd["return_rate"], lumpsum_ann, dd["total_invested"], dd["date"])

        print(f"  最终价值:    {lumpsum['value_after_fee']:>12,.2f} 元")
        print(f"  收益率:      {lumpsum_ret * 100:>12.2f}%")
        print(f"  年化收益率:  {lumpsum_ann * 100:>12.2f}%")
        print(f"  最大回撤:    {max_drawdown(dd['total_value']) * 100:>12.2f}%")
        print(f"  年化波动率:  {ls_em['vol'] * 100:>12.2f}%")
        print(f"  Sharpe 比率: {ls_em['sharpe']:>12.2f}")
        print(f"  Calmar 比率: {ls_em['calmar']:>12.2f}")
        print(f"  胜率:        {ls_em['win_rate'] * 100:>12.2f}%")
        print(f"  盈亏比:      {ls_em['pl_ratio']:>12.2f}")
        diff = total_ret - lumpsum_ret
        winner = "定投胜" if diff > 0 else ("一次性投入胜" if diff < 0 else "持平")
        print(f"  差值:        {diff * 100:>+12.2f}%  ({winner})")
    print(sep)


def print_events(events: list[dict[str, Any]]) -> None:
    if not events:
        return
    print(f"\n止盈事件（共 {len(events)} 次）:")
    print(f"{'#':>3} {'日期':<12} {'净值':>8} {'收益率':>8} {'盈利':>10} {'赎回费':>8} {'原因'}")
    print("─" * 70)
    for i, e in enumerate(events, 1):
        print(
            f"{i:>3} {e['date'].strftime('%Y-%m-%d'):<12} {e['nav']:>8.4f} "
            f"{e['return_rate'] * 100:>7.2f}% {e['profit']:>10.2f} "
            f"{e['redeem_fee']:>8.2f} {e['reason']}"
        )
    total_event_profit = sum(e["profit"] for e in events)
    total_event_fee = sum(e["redeem_fee"] for e in events)
    print(f"{'─' * 70}")
    print(f"{'合计':>3} {'':<12} {'':>8} {'':>8} {total_event_profit:>10.2f} {total_event_fee:>8.2f}")
    print()


def print_detail_table(detail: pd.DataFrame, final_val: float, total_ret: float, events: list[dict[str, Any]]) -> None:
    """交易明细表格（支持分红列自动检测）"""
    total_invest = detail.iloc[-1]["total_invested"]
    if events:
        event_dates = {e["date"] for e in events}
        display = detail[
            (detail["investment"] > 0) | (detail["dividend_units"] > 0) | detail["date"].isin(event_dates)
        ].copy()
    else:
        display = detail

    has_div = display["dividend_units"].sum() > 0
    has_ma = "deviation" in display.columns and display["deviation"].notna().any()

    cols = ["日期", "净值", "投入", "定投份额", "累计份额", "市值", "收益率"]
    widths = [12, 8, 8, 8, 10, 10, 8]
    sep_len = 70
    if has_div:
        cols.insert(4, "分红份额")
        widths.insert(4, 8)
        sep_len = 80
    if has_ma:
        idx = cols.index("投入")
        cols[idx:idx] = ["偏离", "倍数"]
        widths[idx:idx] = [8, 6]
        sep_len += 16

    header = " ".join(f"{c:<{w}}" if i == 0 else f"{c:>{w}}" for i, (c, w) in enumerate(zip(cols, widths)))
    print(header)
    print("─" * sep_len)

    for _, r in display.iterrows():
        cells = [
            f"{r['date'].strftime('%Y-%m-%d'):<12}",
            f"{r['nav']:>8.4f}",
        ]
        if has_ma:
            d = r.get("deviation")
            if pd.notna(d):
                cells.append(f"{d * 100:>8.2f}%")
            else:
                cells.append(f"{'':>8}")
            m = r.get("multiplier")
            if pd.notna(m):
                cells.append(f"{m:>5.1f}x")
            else:
                cells.append(f"{'':>6}")
        cells += [
            f"{r['investment']:>8.0f}",
            f"{r['units_added']:>8.2f}",
        ]
        if has_div:
            cells.append(f"{r['dividend_units']:>8.2f}" if r["dividend_units"] > 0 else f"{'':>8}")
        cells += [
            f"{r['total_units']:>10.2f}",
            f"{r['market_value']:>10.2f}",
            f"{r['return_rate'] * 100:>7.2f}%",
        ]
        print(" ".join(cells))

    print("─" * sep_len)
    summary_cells = [
        f"{'合计':<12}",
        f"{'':>8}",
    ]
    if has_ma:
        summary_cells += [f"{'':>8}", f"{'':>6}"]
    summary_cells += [
        f"{total_invest:>8.0f}",
        f"{'':>8}",
    ]
    if has_div:
        summary_cells.append(f"{'':>8}")
    summary_cells += [
        f"{display.iloc[-1]['total_units']:>10.2f}",
        f"{final_val:>10.2f}",
        f"{total_ret * 100:>7.2f}%",
    ]
    print(" ".join(summary_cells))


def main() -> None:
    setup_logging()
    args = parse_args()
    end_date = args.end or datetime.today().strftime("%Y-%m-%d")

    try:
        nav_df = fetch_fund_data(args.fund, args.start, end_date)
        fund_name = fetch_fund_name(args.fund)
        dividend_df = fetch_dividend_data(args.fund)

        invest_dates = generate_dca_dates(nav_df, args.freq, args.start, end_date, args.day, args.weekday)
        print(f"定投日期: {len(invest_dates)} 期")

        if invest_dates.empty:
            raise BacktestError("未能生成有效的定投日期")

        if args.ma_period > 0:
            if args.index_ma:
                profile = db.fund_profile.load([args.fund])
                tracking_target = profile.get(args.fund, {}).get("跟踪标的")
                if tracking_target:
                    index_info = lookup_index(tracking_target)
                else:
                    index_info = None
                if index_info:
                    idx_code, src, mkt_prefix = index_info
                    print(f"使用指数价格计算均线: {tracking_target} ({idx_code}, {src})")
                    price_df = fetch_index_price(idx_code, src, mkt_prefix)
                    if price_df is not None and not price_df.empty:
                        price_df = price_df.rename(columns={"value": "acc_nav"})
                        price_df["date"] = pd.to_datetime(price_df["date"])
                        if len(price_df) < args.ma_period:
                            print(f"指数价格仅{len(price_df)}条数据，不足{args.ma_period}日均线所需，回退基金净值")
                            ma_nav = nav_df
                        else:
                            s = price_df.set_index("date")["acc_nav"]
                            aligned = nav_df[["date"]].copy()
                            aligned = aligned.merge(s.to_frame(), left_on="date", right_index=True, how="left")
                            aligned["acc_nav"] = aligned["acc_nav"].ffill()
                            first_fund = nav_df["date"].min()
                            warmup = price_df[price_df["date"] < first_fund].copy()
                            if not warmup.empty:
                                warmup = warmup[["date", "acc_nav"]]
                                ma_nav = pd.concat([warmup, aligned], ignore_index=True)
                            else:
                                ma_nav = aligned
                            ma_nav = ma_nav.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
                    else:
                        print("指数价格获取失败，回退基金净值")
                        ma_nav = nav_df
                else:
                    print(f"跟踪标的 '{tracking_target}' 未映射，回退基金净值")
                    ma_nav = nav_df
            else:
                ma_nav = load_ma_buffer(args.fund, args.start, args.ma_period, nav_df)
            ma_tiers, ma_mults = MovingAverageBuyStrategy.MA_MODES.get(
                args.ma_mode, MovingAverageBuyStrategy.MA_MODES["default"]
            )
            if args.ma_tiers is not None:
                ma_tiers = tuple(float(x) for x in args.ma_tiers.split(","))
            if args.ma_multipliers is not None:
                ma_mults = tuple(float(x) for x in args.ma_multipliers.split(","))
            buy_strategy = MovingAverageBuyStrategy(args.amount, args.ma_period, args.fee, ma_nav, ma_tiers, ma_mults)
        elif args.value_avg > 0:
            buy_strategy = ValueAveragingBuyStrategy(args.value_avg, args.va_max_multiple, args.va_min_amount, args.fee)
        else:
            buy_strategy = FixedBuyStrategy(args.amount, args.fee)
        sell_strategy: SellStrategy | None = None
        if args.take_profit > 0:
            sell_strategy = TargetProfitSellStrategy(args.take_profit)
        elif args.stop_invest > 0 and args.trailing_stop > 0:
            sell_strategy = TrailingStopSellStrategy(args.stop_invest, args.trailing_stop)

        detail, events, redeem_fee, final_val = simulate_dca(
            nav_df,
            invest_dates,
            buy_strategy,
            sell_strategy=sell_strategy,
            tp_cycle=args.tp_cycle,
            dividend_df=dividend_df,
        )

        total_invest = detail.iloc[-1]["total_invested"]
        total_ret = (final_val - total_invest) / total_invest
        ann_ret = calc_annualized(total_ret, pd.Timestamp(args.start), pd.Timestamp(end_date))
        mdd = max_drawdown(detail["total_value"])

        lumpsum = calc_lumpsum(nav_df, total_invest, args.start, end_date, args.fee, dividend_df=dividend_df)

        print_summary(
            fund_name,
            args.fund,
            args.start,
            end_date,
            args.freq,
            args.amount,
            args.fee,
            detail,
            redeem_fee,
            final_val,
            total_ret,
            ann_ret,
            mdd,
            lumpsum,
        )
        print_events(events)
        print_detail_table(detail, final_val, total_ret, events)

        if args.output:
            detail.to_csv(args.output, index=False, encoding="utf-8-sig")
            print(f"\n明细已导出: {args.output}")

        plot_results(nav_df, detail, args.fund, fund_name, args.start, end_date, args.chart)
    except BacktestError as e:
        print(e)
        sys.exit(1)


if __name__ == "__main__":
    main()
