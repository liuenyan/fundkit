#!/usr/bin/env python3
"""
中国开放式基金定投回测工具
数据源: 天天基金网 (via AKShare)
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

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


def parse_args():
    p = argparse.ArgumentParser(description="中国开放式基金定投回测工具")
    p.add_argument("--fund", required=True, help="基金代码（6位）")
    p.add_argument("--amount", type=float, required=True, help="每期定投金额")
    p.add_argument(
        "--freq",
        choices=["daily", "weekly", "biweekly", "monthly"],
        default="monthly",
        help="定投频率",
    )
    p.add_argument(
        "--day", type=int, default=10, help="每月定投日 (1-28，仅 monthly 有效)"
    )
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
    return p.parse_args()


def fetch_fund_data(fund_code, start_date, end_date):
    """获取基金历史净值数据（单位净值 + 累计净值）"""
    print(f"获取基金 {fund_code} 历史净值数据 ...")
    try:
        df_unit = ak.fund_open_fund_info_em(
            symbol=fund_code, indicator="单位净值走势"
        )
        df_acc = ak.fund_open_fund_info_em(
            symbol=fund_code, indicator="累计净值走势"
        )
    except Exception as e:
        print(f"获取数据失败: {e}")
        sys.exit(1)

    if df_unit is None or df_unit.empty:
        print("未获取到数据，请检查基金代码是否正确")
        sys.exit(1)

    df_unit = df_unit.rename(
        columns={"净值日期": "date", "单位净值": "unit_nav", "日增长率": "daily_return"}
    )
    df_acc = df_acc.rename(columns={"净值日期": "date", "累计净值": "acc_nav"})

    df = df_unit.merge(df_acc, on="date", how="left")
    df["date"] = pd.to_datetime(df["date"])
    df["unit_nav"] = pd.to_numeric(df["unit_nav"], errors="coerce")
    df["acc_nav"] = pd.to_numeric(df["acc_nav"], errors="coerce")
    df = df.sort_values("date").reset_index(drop=True)

    mask = (df["date"] >= pd.Timestamp(start_date)) & (
        df["date"] <= pd.Timestamp(end_date)
    )
    df = df[mask].reset_index(drop=True)

    if df.empty:
        print(f"错误：{start_date} ~ {end_date} 范围内无数据")
        sys.exit(1)

    print(f"获取到 {len(df)} 条净值记录")
    return df


def fetch_fund_name(fund_code):
    """获取基金简称"""
    try:
        df = ak.fund_name_em()
        row = df[df["基金代码"] == fund_code]
        if not row.empty:
            return row.iloc[0]["基金简称"]
    except Exception:
        pass
    return fund_code


def generate_dca_dates(nav_df, freq, start_date, end_date, day=10, weekday=1):
    """生成定投日期序列并匹配到最近的交易日"""
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    nav_dates_set = set(nav_df["date"])

    if freq == "daily":
        dates = sorted(d for d in nav_dates_set if start <= d <= end)
        return pd.DatetimeIndex(dates)

    candidates = []
    if freq in ("weekly", "biweekly"):
        week_dates = pd.date_range(
            start, end, freq=f'W-{WEEKDAY_MAP[weekday]}'
        )
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


def get_redeem_rate(hold_days, schedule=None):
    """根据持有天数查赎回费率"""
    if schedule is None:
        schedule = DEFAULT_REDEEM_SCHEDULE
    prev = 0
    for threshold, rate in schedule:
        if prev < hold_days <= threshold:
            return rate
        prev = threshold
    return 0.0


def simulate_dca(nav_df, invest_dates, amount, purchase_rate, redeem_schedule=None):
    """执行定投模拟"""
    nav_dict = dict(zip(nav_df["date"], nav_df["unit_nav"]))

    records = []
    total_units = 0.0
    total_cost = 0.0

    for date in invest_dates:
        nav = nav_dict.get(date)
        if nav is None:
            continue

        actual = amount * (1 - purchase_rate)
        units = actual / nav
        total_units += units
        total_cost += amount
        market_value = total_units * nav

        records.append(
            {
                "date": date,
                "nav": nav,
                "investment": amount,
                "units_added": units,
                "total_units": total_units,
                "total_cost": total_cost,
                "market_value": market_value,
                "profit": market_value - total_cost,
                "return_rate": (market_value - total_cost) / total_cost,
            }
        )

    detail = pd.DataFrame(records)
    if detail.empty:
        print("错误：未生成有效的定投记录")
        sys.exit(1)

    latest_date = max(nav_dict.keys())
    latest_nav = nav_dict[latest_date]

    total_redeem_fee = 0.0
    for _, row in detail.iterrows():
        hold = (latest_date - row["date"]).days
        fee_rate = get_redeem_rate(hold, redeem_schedule)
        total_redeem_fee += row["units_added"] * latest_nav * fee_rate

    final_value_before = detail.iloc[-1]["market_value"]
    final_value_after = final_value_before - total_redeem_fee

    return detail, total_redeem_fee, final_value_after


def calc_annualized(ret, start, end):
    days = (end - start).days
    if days <= 0:
        return 0.0
    return (1 + ret) ** (365 / days) - 1


def max_drawdown(series):
    peak = series.expanding().max()
    dd = (series - peak) / peak
    return dd.min()


def calc_lumpsum(nav_df, amount, start_date, end_date, purchase_rate, redeem_schedule=None):
    """一次性投入收益计算"""
    df = nav_df.copy()
    df = df[df["date"] >= pd.Timestamp(start_date)].reset_index(drop=True)
    if df.empty:
        return None

    first = df.iloc[0]
    actual = amount * (1 - purchase_rate)
    units = actual / first["unit_nav"]

    end = pd.Timestamp(end_date)
    end_row = df[df["date"] <= end]
    if end_row.empty:
        return None
    last = end_row.iloc[-1]

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


def _setup_cjk_font():
    """设置中文字体，找到第一个可用的 CJK 字体"""
    import matplotlib.font_manager as fm
    import os

    paths = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        os.path.expanduser("~/.fonts/NotoSansSC.ttf"),
        os.path.expanduser("~/.fonts/wqy-microhei.ttc"),
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    ]
    for p in paths:
        if os.path.exists(p):
            fm.fontManager.addfont(p)
            break

    prefer = ["Noto Sans CJK SC", "Noto Sans SC", "WenQuanYi Micro Hei", "Noto Sans CJK"]
    names = {f.name for f in fm.fontManager.ttflist}
    for want in prefer:
        for n in names:
            if want in n:
                plt.rcParams["font.family"] = n
                return n
    # fallback: any font with CJK keywords
    for n in names:
        if any(kw in n.lower() for kw in ["cjk", "hei", "song", "ming", "noto"]):
            plt.rcParams["font.family"] = n
            return n
    return None


def plot_results(nav_df, detail, fund_code, fund_name, start_date, end_date, chart_dir):
    """生成分析图表"""
    os.makedirs(chart_dir, exist_ok=True)

    _setup_cjk_font()
    plt.rcParams["axes.unicode_minus"] = False

    assert not nav_df.empty, "nav_df 为空"
    assert "unit_nav" in nav_df.columns, f"nav_df 缺少 unit_nav: {list(nav_df.columns)}"
    assert "acc_nav" in nav_df.columns, f"nav_df 缺少 acc_nav: {list(nav_df.columns)}"
    assert nav_df["unit_nav"].notna().any(), "unit_nav 全是 NaN"
    assert nav_df["acc_nav"].notna().any(), "acc_nav 全是 NaN"
    if not detail.empty:
        assert "total_cost" in detail.columns
        assert "total_units" in detail.columns
        assert detail["total_units"].iloc[-1] > 0, "total_units 未累计"
        avg = detail["total_cost"] / detail["total_units"]
        assert avg.notna().any(), "avg 全是 NaN"

    fig, axes = plt.subplots(2, 1, figsize=(12, 10), sharex=False)

    # --- 子图1: 净值走势与定投成本 ---
    ax1 = axes[0]
    ax1.plot(nav_df["date"], nav_df["unit_nav"], color="steelblue", lw=1.2,
             alpha=0.9, label="单位净值")
    ax1.plot(nav_df["date"], nav_df["acc_nav"], color="steelblue", lw=0.8,
             ls="--", alpha=0.6, label="累计净值")

    if not detail.empty:
        avg = detail["total_cost"] / detail["total_units"]
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

        roll_max = detail["market_value"].expanding().max()
        dd = (detail["market_value"] - roll_max) / roll_max * 100
        ax2.fill_between(detail["date"].values, 0, dd.values,
                         alpha=0.25, color="firebrick", label="回撤", step="pre")

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


def main():
    args = parse_args()
    end_date = args.end or datetime.today().strftime("%Y-%m-%d")

    nav_df = fetch_fund_data(args.fund, args.start, end_date)
    fund_name = fetch_fund_name(args.fund)

    invest_dates = generate_dca_dates(
        nav_df, args.freq, args.start, end_date, args.day, args.weekday
    )
    print(f"定投日期: {len(invest_dates)} 期")

    if invest_dates.empty:
        print("错误：未能生成有效的定投日期")
        sys.exit(1)

    detail, redeem_fee, final_val = simulate_dca(
        nav_df, invest_dates, args.amount, args.fee
    )

    total_invest = detail.iloc[-1]["total_cost"]
    final_val_before = detail.iloc[-1]["market_value"]
    total_ret = (final_val - total_invest) / total_invest
    ann_ret = calc_annualized(total_ret, pd.Timestamp(args.start), pd.Timestamp(end_date))
    mdd = max_drawdown(detail["market_value"])

    lumpsum = calc_lumpsum(
        nav_df, total_invest, args.start, end_date, args.fee
    )

    sep = "=" * 52
    print(f"""
{sep}
定投回测结果
{sep}
基金: {fund_name}（{args.fund}）
回测期间: {args.start}  →  {end_date}
定投频率: {args.freq:<8}  每期: {args.amount:>8,.2f} 元
申购费率: {args.fee * 100:.2f}%

{'─' * 52}
总投入:        {total_invest:>12,.2f} 元
期末市值:      {final_val_before:>12,.2f} 元
赎回费:        {redeem_fee:>12,.2f} 元
实际到账:      {final_val:>12,.2f} 元
总收益率:      {total_ret * 100:>12.2f}%
年化收益率:    {ann_ret * 100:>12.2f}%
最大回撤:      {mdd * 100:>12.2f}%

{'─' * 52}
一次性投入对比（同等金额 {total_invest:,.2f} 元）:
""")
    if lumpsum:
        print(f"  最终价值:    {lumpsum['value_after_fee']:>12,.2f} 元")
        print(f"  收益率:      {lumpsum['return_rate'] * 100:>12.2f}%")
        diff = total_ret - lumpsum["return_rate"]
        winner = "定投胜" if diff > 0 else ("一次性投入胜" if diff < 0 else "持平")
        print(f"  差值:        {diff * 100:>+12.2f}%  ({winner})")
    print(sep)

    print()
    print(f"{'日期':<12} {'净值':>8} {'投入':>8} {'份额':>8} {'累计份额':>10} {'市值':>10} {'收益率':>8}")
    print("─" * 70)
    for _, r in detail.iterrows():
        print(
            f"{r['date'].strftime('%Y-%m-%d'):<12} {r['nav']:>8.4f} "
            f"{r['investment']:>8.0f} {r['units_added']:>8.2f} "
            f"{r['total_units']:>10.2f} {r['market_value']:>10.2f} "
            f"{r['return_rate'] * 100:>7.2f}%"
        )
    print("─" * 70)
    print(
        f"{'合计':<12} {'':>8} {total_invest:>8.0f} {'':>8} "
        f"{detail.iloc[-1]['total_units']:>10.2f} "
        f"{final_val:>10.2f} {total_ret * 100:>7.2f}%"
    )

    if args.output:
        detail.to_csv(args.output, index=False, encoding="utf-8-sig")
        print(f"\n明细已导出: {args.output}")

    plot_results(nav_df, detail, args.fund, fund_name, args.start, end_date, args.chart)


if __name__ == "__main__":
    main()
