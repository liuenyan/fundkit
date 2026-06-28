#!/usr/bin/env python3
"""
中国开放式基金定投回测工具
数据源: 天天基金网 (via AKShare)
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from typing import Any, TypedDict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from backend.charting import create_chart
from backend.em_fetcher import fetch_nav_data
from backend.strategy import (
    BuyStrategy,
    DCAPosition,
    FixedBuyStrategy,
    SellStrategy,
    TargetProfitSellStrategy,
    TrailingStopSellStrategy,
    ValueAveragingBuyStrategy,
)

import akshare as ak
import db


INF = float("inf")

DEFAULT_REDEEM_SCHEDULE = [
    (7, 0.0150),
    (30, 0.0075),
    (365, 0.0050),
    (730, 0.0025),
    (INF, 0.0),
]

WEEKDAY_MAP = {1: "MON", 2: "TUE", 3: "WED", 4: "THU", 5: "FRI"}


class LumpSumResult(TypedDict):
    amount: float
    units: float
    value_before_fee: float
    redeem_fee: float
    value_after_fee: float
    return_rate: float


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

    p.add_argument("--value-avg", type=float, default=0, help="【价值平均】每期市值增长目标 (如 1000 表示每月目标增长 1000 元市值)")
    p.add_argument("--va-max-multiple", type=float, default=4.0, help="【价值平均】每期最大投入倍数 (默认 4 倍)")
    p.add_argument("--va-min-amount", type=float, default=10.0, help="【价值平均】最低申购金额 (默认 10 元)")
    return p.parse_args()


def fetch_fund_data(fund_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """获取基金历史净值数据（单位净值 + 累计净值）"""
    print(f"获取基金 {fund_code} 历史净值数据 ...")
    try:
        df = fetch_nav_data(fund_code)
    except Exception as e:
        print(f"获取数据失败: {e}")
        sys.exit(1)

    if df.empty:
        print("未获取到数据，请检查基金代码是否正确")
        sys.exit(1)

    df["date"] = pd.to_datetime(df["净值日期"])
    df["unit_nav"] = pd.to_numeric(df["单位净值"], errors="coerce")
    df["acc_nav"] = pd.to_numeric(df["累计净值"], errors="coerce")
    df["daily_return"] = pd.to_numeric(df["日增长率"], errors="coerce")

    mask = (df["date"] >= pd.Timestamp(start_date)) & (df["date"] <= pd.Timestamp(end_date))
    df = df[mask].reset_index(drop=True)

    if df.empty:
        print(f"错误：{start_date} ~ {end_date} 范围内无数据")
        sys.exit(1)

    print(f"获取到 {len(df)} 条净值记录")
    return df


def fetch_dividend_data(fund_code: str) -> pd.DataFrame:
    """获取基金真实分红事件（天天基金网）"""
    try:
        df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="分红送配详情", period="成立来")
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty or "暂无" in str(df.iloc[0, 0]):
        return pd.DataFrame()
    df["每份分红"] = df["每份分红"].str.extract(r"([\d.]+)").astype(float)
    df["除息日"] = pd.to_datetime(df["除息日"])
    return df[["除息日", "每份分红"]].sort_values("除息日").reset_index(drop=True)


def fetch_fund_name(fund_code: str) -> str:
    """获取基金简称"""
    df = db.fund_catalog.load()
    if df is not None:
        row = df[df["基金代码"] == fund_code]
        if not row.empty:
            return row.iloc[0]["基金简称"]
    return fund_code


def generate_dca_dates(nav_df: pd.DataFrame, freq: str, start_date: str, end_date: str, day: int = 10, weekday: int = 1) -> pd.DatetimeIndex:
    """生成定投日期序列并匹配到最近的交易日"""
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    nav_dates_set = set(nav_df["date"])

    if freq == "daily":
        dates = sorted(d for d in nav_dates_set if start <= d <= end)
        return pd.DatetimeIndex(dates)

    candidates = []
    if freq in ("weekly", "biweekly"):
        week_dates = pd.date_range(start, end, freq=f"W-{WEEKDAY_MAP[weekday]}")
        step = 2 if freq == "biweekly" else 1
        candidates = list(week_dates[::step])
    elif freq == "monthly":
        month_starts = pd.date_range(start.replace(day=1), end, freq="MS")
        for ms in month_starts:
            try:
                cand = ms.replace(day=min(day, 28))
            except ValueError:
                cand = ms.replace(day=28)
            if cand >= start:
                candidates.append(cand)

    result = []
    for cand in candidates:
        for offset in range(10):
            test = cand + timedelta(days=offset)
            if test in nav_dates_set:
                result.append(test)
                break

    return pd.DatetimeIndex(sorted(set(result)))


def get_redeem_rate(hold_days: int, schedule: list[tuple[int, float]] | None = None) -> float:
    """根据持有天数查赎回费率"""
    if schedule is None:
        schedule = DEFAULT_REDEEM_SCHEDULE
    prev = 0
    for threshold, rate in schedule:
        if prev < hold_days <= threshold:
            return rate
        prev = threshold
    return 0.0


def build_dividend_dict(dividend_df: pd.DataFrame | None) -> dict[pd.Timestamp, float]:
    """从分红数据构建 {除息日: 每份分红} 字典"""
    if dividend_df is None or dividend_df.empty:
        return {}
    return dict(zip(dividend_df["除息日"], dividend_df["每份分红"]))


def reinvest_dividends(
    units: float, nav: float, date: pd.Timestamp,
    dividend_dict: dict[pd.Timestamp, float],
) -> float:
    """计算分红再投资新增份额"""
    if units > 0 and date in dividend_dict:
        return units * dividend_dict[date] / nav
    return 0.0


def calc_redeem_fee(
    fee_batches: list[dict],
    date: pd.Timestamp,
    nav: float,
    redeem_schedule: list[tuple[int, float]] | None = None,
) -> float:
    """计算全部申购批次在指定日期的赎回费"""
    fee = 0.0
    for b in fee_batches:
        hold = (date - b["date"]).days
        rate = get_redeem_rate(hold, redeem_schedule)
        fee += b["units"] * nav * rate
    return fee


def simulate_dca(
    nav_df: pd.DataFrame,
    invest_dates: pd.DatetimeIndex,
    buy_strategy: BuyStrategy,
    sell_strategy: SellStrategy | None = None,
    tp_cycle: bool = False,
    redeem_schedule: list[tuple[int, float]] | None = None,
    dividend_df: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]], float, float]:
    """执行定投模拟"""
    nav_dict = dict(zip(nav_df["date"], nav_df["unit_nav"]))
    dividend_dict = build_dividend_dict(dividend_df)

    stop_profit_on = sell_strategy is not None
    invest_set = set(invest_dates)
    pos = DCAPosition()
    records: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    for date in nav_df["date"]:
        nav = nav_dict[date]

        inv_today = 0.0
        unit_added = 0.0
        div_units = 0.0

        # ── 分红再投资 ──
        div_units = reinvest_dividends(pos.units, nav, date, dividend_dict)
        if div_units > 0:
            pos.units += div_units

        # ── 申购（委托买入策略）──
        action = buy_strategy.should_buy(date, nav, pos, invest_set)
        if action.amount > 0:
            net = action.amount * (1 - action.fee_rate)
            unit_added = net / nav
            pos.units += unit_added
            pos.cost += action.amount
            pos.total_invested += action.amount
            inv_today = action.amount
            pos.fee_batches.append({"date": date, "units": unit_added})

        # ── 当前持仓市值 ──
        if pos.units > 0:
            mkt_value = pos.units * nav
            round_return = (mkt_value - pos.cost) / pos.cost
        else:
            mkt_value = 0.0
            round_return = 0.0

        if pos.units > 0 and round_return > pos.peak_return:
            pos.peak_return = round_return

        # ── 卖出检查（委托卖出策略）──
        should_sell = False
        sell_reason = ""

        if sell_strategy is not None:
            signal = sell_strategy.evaluate(date, nav, pos, mkt_value, round_return)
            if signal.stop_buying:
                pos.is_active = False
            if signal.should_sell:
                should_sell = True
                sell_reason = signal.reason

        if should_sell:
            fee = calc_redeem_fee(pos.fee_batches, date, nav, redeem_schedule)
            net = mkt_value - fee
            events.append({
                "date": date,
                "nav": nav,
                "return_rate": round_return,
                "round_cost": pos.cost,
                "profit": mkt_value - pos.cost,
                "redeem_fee": fee,
                "net_proceeds": net,
                "reason": sell_reason,
            })
            pos.total_recovered += net
            pos.units = 0.0
            pos.cost = 0.0
            mkt_value = 0.0
            round_return = 0.0
            pos.peak_return = -INF
            pos.fee_batches = []
            pos.is_active = tp_cycle
            sell_strategy.on_reset()
            buy_strategy.on_reset()

        # ── 整体组合指标 ──
        total_value = mkt_value + pos.total_recovered
        overall_profit = total_value - pos.total_invested
        overall_return = overall_profit / pos.total_invested if pos.total_invested > 0 else 0.0

        # 无止盈策略只记录定投日和分红日
        if not stop_profit_on and date not in invest_set and div_units == 0:
            continue

        records.append({
            "date": date,
            "nav": nav,
            "investment": inv_today,
            "units_added": unit_added,
            "dividend_units": div_units,
            "total_units": pos.units,
            "total_cost": pos.cost,
            "market_value": mkt_value,
            "profit": overall_profit,
            "return_rate": overall_return,
            "total_invested": pos.total_invested,
            "total_value": total_value,
        })

    detail = pd.DataFrame(records)
    if detail.empty:
        print("错误：未生成有效的定投记录")
        sys.exit(1)

    # ── 期末赎回费 ──
    final_redeem_fee = 0.0
    if pos.units > 0 and pos.fee_batches:
        last_row = detail.iloc[-1]
        final_redeem_fee = calc_redeem_fee(pos.fee_batches, last_row["date"], last_row["nav"], redeem_schedule)

    last_market_value = detail.iloc[-1]["market_value"]
    final_value = pos.total_recovered + (last_market_value - final_redeem_fee)
    return detail, events, final_redeem_fee, final_value


def calc_annualized(ret: float, start: pd.Timestamp, end: pd.Timestamp) -> float:
    days = (end - start).days
    if days <= 0:
        return 0.0
    return (1 + ret) ** (365 / days) - 1


def max_drawdown(series: pd.Series) -> float:
    peak = series.expanding().max()
    dd = (series - peak) / peak
    return dd.min()


def calc_lumpsum(nav_df: pd.DataFrame, amount: float, start_date: str, end_date: str, purchase_rate: float, redeem_schedule: list[tuple[int, float]] | None = None, dividend_df: pd.DataFrame | None = None) -> LumpSumResult | None:
    """一次性投入收益计算（基于真实分红数据再投资）"""
    df = nav_df.loc[nav_df["date"] >= pd.Timestamp(start_date)].reset_index(drop=True)
    if df.empty:
        return None

    first = df.iloc[0]
    actual = amount * (1 - purchase_rate)
    units = actual / first["unit_nav"]
    dividend_dict = build_dividend_dict(dividend_df)

    for _, row in df.iterrows():
        units += reinvest_dividends(units, row["unit_nav"], row["date"], dividend_dict)

    last = df.iloc[-1]
    val_before = units * last["unit_nav"]
    hold = (last["date"] - first["date"]).days
    fee_rate = get_redeem_rate(hold, redeem_schedule)
    fee = val_before * fee_rate
    val_after = val_before - fee

    return {
        "amount": amount,
        "units": units,
        "value_before_fee": val_before,
        "redeem_fee": fee,
        "value_after_fee": val_after,
        "return_rate": (val_after - amount) / amount,
    }


def plot_results(nav_df: pd.DataFrame, detail: pd.DataFrame, fund_code: str, fund_name: str, start_date: str, end_date: str, chart_dir: str) -> None:
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


def print_summary(
    fund_name: str, fund_code: str, start: str, end: str, freq: str, amount: float, fee: float,
    detail: pd.DataFrame, redeem_fee: float, final_val: float,
    total_ret: float, ann_ret: float, mdd: float,
    lumpsum: LumpSumResult | None,
) -> None:
    total_invest = detail.iloc[-1]["total_invested"]
    portfolio_value = detail.iloc[-1]["total_value"]
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

{"─" * 52}
一次性投入对比（同等金额 {total_invest:,.2f} 元）:
""")
    if lumpsum:
        print(f"  最终价值:    {lumpsum['value_after_fee']:>12,.2f} 元")
        print(f"  收益率:      {lumpsum['return_rate'] * 100:>12.2f}%")
        diff = total_ret - lumpsum["return_rate"]
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
    cols = ["日期", "净值", "投入", "定投份额", "累计份额", "市值", "收益率"]
    widths = [12, 8, 8, 8, 10, 10, 8]
    sep_len = 70
    if has_div:
        cols.insert(4, "分红份额")
        widths.insert(4, 8)
        sep_len = 80

    header = " ".join(f"{c:<{w}}" if i == 0 else f"{c:>{w}}" for i, (c, w) in enumerate(zip(cols, widths)))
    print(header)
    print("─" * sep_len)

    for _, r in display.iterrows():
        cells = [
            f"{r['date'].strftime('%Y-%m-%d'):<12}",
            f"{r['nav']:>8.4f}",
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
    args = parse_args()
    end_date = args.end or datetime.today().strftime("%Y-%m-%d")

    nav_df = fetch_fund_data(args.fund, args.start, end_date)
    fund_name = fetch_fund_name(args.fund)
    dividend_df = fetch_dividend_data(args.fund)

    invest_dates = generate_dca_dates(nav_df, args.freq, args.start, end_date, args.day, args.weekday)
    print(f"定投日期: {len(invest_dates)} 期")

    if invest_dates.empty:
        print("错误：未能生成有效的定投日期")
        sys.exit(1)

    # 构造策略对象
    if args.value_avg > 0:
        buy_strategy = ValueAveragingBuyStrategy(
            args.value_avg, args.va_max_multiple, args.va_min_amount, args.fee)
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

    print_summary(fund_name, args.fund, args.start, end_date, args.freq, args.amount, args.fee,
                  detail, redeem_fee, final_val, total_ret, ann_ret, mdd, lumpsum)
    print_events(events)
    print_detail_table(detail, final_val, total_ret, events)

    if args.output:
        detail.to_csv(args.output, index=False, encoding="utf-8-sig")
        print(f"\n明细已导出: {args.output}")

    plot_results(nav_df, detail, args.fund, fund_name, args.start, end_date, args.chart)


if __name__ == "__main__":
    main()
