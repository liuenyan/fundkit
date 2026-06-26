#!/usr/bin/env python3
"""
中国开放式基金定投回测工具
数据源: 天天基金网 (via AKShare)
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from tools.cjk_font import setup_cjk_font
from backend.strategy import (
    BuyStrategy,
    DCAPosition,
    FixedBuyStrategy,
    SellStrategy,
    TargetProfitSellStrategy,
    TrailingStopSellStrategy,
)

try:
    import akshare as ak
except ImportError:
    print("请先安装依赖: pip install -r requirements.txt")
    sys.exit(1)


DEFAULT_REDEEM_SCHEDULE = [
    (7, 0.0150),
    (30, 0.0075),
    (365, 0.0050),
    (730, 0.0025),
    (float("inf"), 0.0),
]

WEEKDAY_MAP = {1: "MON", 2: "TUE", 3: "WED", 4: "THU", 5: "FRI"}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="中国开放式基金定投回测工具")
    p.add_argument("--fund", required=True, help="基金代码（6位）")
    p.add_argument("--amount", type=float, required=True, help="每期定投金额")
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
    return p.parse_args()


def fetch_fund_data(fund_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """获取基金历史净值数据（单位净值 + 累计净值）"""
    print(f"获取基金 {fund_code} 历史净值数据 ...")
    try:
        df_unit = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
        df_acc = ak.fund_open_fund_info_em(symbol=fund_code, indicator="累计净值走势")
    except Exception as e:
        print(f"获取数据失败: {e}")
        sys.exit(1)

    if df_unit is None or df_unit.empty:
        print("未获取到数据，请检查基金代码是否正确")
        sys.exit(1)

    df_unit = df_unit.rename(columns={"净值日期": "date", "单位净值": "unit_nav", "日增长率": "daily_return"})
    df_acc = df_acc.rename(columns={"净值日期": "date", "累计净值": "acc_nav"})

    df = df_unit.merge(df_acc, on="date", how="left")
    df["date"] = pd.to_datetime(df["date"])
    df["unit_nav"] = pd.to_numeric(df["unit_nav"], errors="coerce")
    df["acc_nav"] = pd.to_numeric(df["acc_nav"], errors="coerce")
    df = df.sort_values("date").reset_index(drop=True)

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
    try:
        import db

        df = db.fund_catalog.load()
        if df is not None:
            row = df[df["基金代码"] == fund_code]
            if not row.empty:
                return row.iloc[0]["基金简称"]
    except Exception:
        pass
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
        cur = start.replace(day=1)
        while cur <= end:
            try:
                cand = cur.replace(day=min(day, 28))
            except ValueError:
                cand = cur.replace(day=28)
            if cand >= start:
                candidates.append(cand)
            y = cur.year + (cur.month // 12)
            m = cur.month % 12 + 1
            cur = pd.Timestamp(year=y, month=m, day=1)
        candidates = sorted(set(candidates))

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


def simulate_dca(
    nav_df: pd.DataFrame,
    invest_dates: pd.DatetimeIndex,
    amount: float,
    purchase_rate: float,
    redeem_schedule: list[tuple[int, float]] | None = None,
    take_profit: float | None = None,
    tp_cycle: bool = False,
    stop_invest: float | None = None,
    trailing_stop: float | None = None,
    dividend_df: pd.DataFrame | None = None,
    buy_strategy: BuyStrategy | None = None,
    sell_strategies: list[SellStrategy] | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]], float, float]:
    """执行定投模拟

    Parameters
    ----------
    buy_strategy / sell_strategies : 策略对象（优先使用）
    amount/purchase_rate/take_profit/... : 平参（当策略对象为 None 时自动构造）
    """
    nav_dict = dict(zip(nav_df["date"], nav_df["unit_nav"]))
    dividend_dict = build_dividend_dict(dividend_df)

    # 从平参自动构造策略
    if buy_strategy is None:
        buy_strategy = FixedBuyStrategy(amount, purchase_rate)
    if sell_strategies is None:
        sell_strategies = []
        if take_profit is not None:
            sell_strategies.append(TargetProfitSellStrategy(take_profit))
        if stop_invest is not None and trailing_stop is not None:
            sell_strategies.append(TrailingStopSellStrategy(stop_invest, trailing_stop))

    stop_profit_on = bool(sell_strategies)
    invest_set = set(invest_dates)
    pos = DCAPosition()
    records: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    for d in nav_df["date"]:
        date = pd.Timestamp(d)
        nav = nav_dict.get(date)
        if nav is None:
            continue

        inv_today = 0.0
        unit_added = 0.0
        div_units = 0.0

        # ── 分红再投资 ──
        if pos.units > 0 and date in dividend_dict:
            div_units = pos.units * dividend_dict[date] / nav
            pos.units += div_units

        # ── 申购（委托买入策略）──
        action = buy_strategy.should_buy(date, nav, pos, invest_set)
        if action.amount > 0:
            actual = action.amount * (1 - purchase_rate)
            unit_added = actual / nav
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

        # ── 卖出检查（委托卖出策略列表，先触发先执行）──
        should_sell = False
        sell_reason = ""
        triggered_strat: SellStrategy | None = None

        for strat in sell_strategies:
            signal = strat.evaluate(date, nav, pos, mkt_value, round_return)
            if signal.stop_buying:
                pos.is_active = False
            if signal.should_sell:
                should_sell = True
                sell_reason = signal.reason
                triggered_strat = strat
                break

        if should_sell:
            fee = 0.0
            for b in pos.fee_batches:
                hold = (date - b["date"]).days
                rate = get_redeem_rate(hold, redeem_schedule)
                fee += b["units"] * nav * rate
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
            pos.peak_return = -float("inf")
            pos.fee_batches = []
            pos.is_active = tp_cycle
            if triggered_strat is not None:
                triggered_strat.on_reset()

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
        for b in pos.fee_batches:
            hold = (last_row["date"] - b["date"]).days
            rate = get_redeem_rate(hold, redeem_schedule)
            final_redeem_fee += b["units"] * last_row["nav"] * rate

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


def calc_lumpsum(nav_df: pd.DataFrame, amount: float, start_date: str, end_date: str, purchase_rate: float, redeem_schedule: list[tuple[int, float]] | None = None, dividend_df: pd.DataFrame | None = None) -> dict[str, Any] | None:
    """一次性投入收益计算（基于真实分红数据再投资）"""
    df = nav_df.copy()
    df = df[df["date"] >= pd.Timestamp(start_date)].reset_index(drop=True)
    if df.empty:
        return None

    first = df.iloc[0]
    actual = amount * (1 - purchase_rate)
    units = actual / first["unit_nav"]
    dividend_dict = build_dividend_dict(dividend_df)

    for _, row in df.iterrows():
        if units > 0 and row["date"] in dividend_dict:
            units += units * dividend_dict[row["date"]] / row["unit_nav"]

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
    """生成分析图表"""
    os.makedirs(chart_dir, exist_ok=True)

    setup_cjk_font()

    assert not nav_df.empty, "nav_df 为空"
    assert "unit_nav" in nav_df.columns, f"nav_df 缺少 unit_nav: {list(nav_df.columns)}"
    assert "acc_nav" in nav_df.columns, f"nav_df 缺少 acc_nav: {list(nav_df.columns)}"
    assert nav_df["unit_nav"].notna().any(), "unit_nav 全是 NaN"
    assert nav_df["acc_nav"].notna().any(), "acc_nav 全是 NaN"
    if not detail.empty:
        assert "total_cost" in detail.columns
        assert "total_units" in detail.columns

    fig, axes = plt.subplots(2, 1, figsize=(12, 10), sharex=False)

    # --- 子图1: 净值走势与定投成本 ---
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

    # --- 子图2: 定投收益率与回撤 ---
    ax2 = axes[1]
    if not detail.empty:
        ret = detail["return_rate"] * 100
        ax2.plot(detail["date"], ret, color="forestgreen", lw=2, label="定投收益率")

        dd_col = "total_value" if "total_value" in detail.columns else "market_value"
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
    path = os.path.join(chart_dir, f"{fund_code}_dca_backtest.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"图表已保存: {path}")


def print_summary(
    fund_name: str, fund_code: str, start: str, end: str, freq: str, amount: float, fee: float,
    total_invest: float, portfolio_value: float, redeem_fee: float, final_val: float,
    total_ret: float, ann_ret: float, mdd: float,
    lumpsum: dict[str, Any] | None,
) -> None:
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


def print_detail_table(detail: pd.DataFrame, total_invest: float, final_val: float, total_ret: float, stop_profit_on: bool, events: list[dict[str, Any]]) -> None:
    """交易明细表格（支持分红列自动检测）"""
    if stop_profit_on:
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

    header = " ".join(f"{c:>{w}}" if w == widths[-1] else f"{c:<{w}}" if i == 0 else f"{c:>{w}}" for i, (c, w) in enumerate(zip(cols, widths)))
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
    buy_strategy = FixedBuyStrategy(args.amount, args.fee)
    sell_strategies: list[SellStrategy] = []
    if args.take_profit > 0:
        sell_strategies.append(TargetProfitSellStrategy(args.take_profit))
    if args.stop_invest > 0 and args.trailing_stop > 0:
        sell_strategies.append(TrailingStopSellStrategy(args.stop_invest, args.trailing_stop))
    stop_profit_on = bool(sell_strategies)

    detail, events, redeem_fee, final_val = simulate_dca(
        nav_df,
        invest_dates,
        args.amount,
        args.fee,
        take_profit=None,
        tp_cycle=args.tp_cycle,
        stop_invest=None,
        trailing_stop=None,
        dividend_df=dividend_df,
        buy_strategy=buy_strategy,
        sell_strategies=sell_strategies if sell_strategies else None,
    )

    total_invest = detail.iloc[-1]["total_invested"]
    portfolio_value = detail.iloc[-1]["total_value"]
    total_ret = (final_val - total_invest) / total_invest
    ann_ret = calc_annualized(total_ret, pd.Timestamp(args.start), pd.Timestamp(end_date))
    mdd = max_drawdown(detail["total_value"])

    lumpsum = calc_lumpsum(nav_df, total_invest, args.start, end_date, args.fee, dividend_df=dividend_df)

    print_summary(fund_name, args.fund, args.start, end_date, args.freq, args.amount, args.fee,
                  total_invest, portfolio_value, redeem_fee, final_val, total_ret, ann_ret, mdd, lumpsum)
    print_events(events)
    print_detail_table(detail, total_invest, final_val, total_ret, stop_profit_on, events)

    if args.output:
        detail.to_csv(args.output, index=False, encoding="utf-8-sig")
        print(f"\n明细已导出: {args.output}")

    plot_results(nav_df, detail, args.fund, fund_name, args.start, end_date, args.chart)


if __name__ == "__main__":
    main()
