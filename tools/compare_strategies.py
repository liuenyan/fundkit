"""
多基金 × 多起点 × 多策略 定投对比工具

手动指定场景:
  ./venv/bin/python -m tools.compare_strategies \\
    --funds 110026,110020,160119 \\
    --scenarios "熊市底部:2019-01-10,市场平均:2020-04-10,牛市顶部:2021-07-09"

自动寻找场景（需缓存或网络）:
  ./venv/bin/python -m tools.compare_strategies \\
    --funds 110026 \\
    --auto-scenarios 110026 \\
    --scenarios-spec "牛市顶部:2021,熊市底部:2018-2019,市场平均:2020"
"""

import argparse
import sys
from datetime import datetime

import pandas as pd

import db
from backend.dca_backtest import (
    BacktestError,
    fetch_dividend_data,
    fetch_fund_data,
    generate_dca_dates,
    simulate_dca,
    calc_lumpsum,
)
from backend.strategy import (
    FixedBuyStrategy,
    MovingAverageBuyStrategy,
    ValueAveragingBuyStrategy,
)
from tools.stats import calc_annualized, max_drawdown
from tools.find_scenarios import find_scenarios


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="多基金 × 多起点 × 多策略 定投对比")
    p.add_argument("--funds", required=True, help="基金代码，逗号分隔 (如 110026,110020)")
    p.add_argument("--scenarios", default=None,
                   help="场景列表 '名称:日期' 逗号分隔 (如 熊市底部:2019-01-10,牛市顶部:2021-07-09)")
    p.add_argument("--auto-scenarios", default=None,
                   help="自动寻找场景的参考基金代码（启用后忽略 --scenarios）")
    p.add_argument("--scenarios-spec", default="牛市顶部:2021,熊市底部:2018-2019,市场平均:2020",
                   help="配合 --auto-scenarios 使用，指定场景参数 (默认 牛市顶部:2021,熊市底部:2018-2019,市场平均:2020)")
    p.add_argument("--amount", type=float, default=1000, help="每期基准金额 (默认 1000)")
    p.add_argument("--freq", choices=["daily", "weekly", "biweekly", "monthly"], default="monthly")
    p.add_argument("--fee", type=float, default=0.0015, help="申购费率 (默认 0.0015)")
    p.add_argument("--ma-period", type=int, default=250, help="均线周期 (默认 250)")
    p.add_argument("--va-target", type=float, default=1000, help="价值平均目标增长额 (默认 1000)")
    p.add_argument("--va-max-multiple", type=float, default=4.0, help="价值平均最大倍数 (默认 4)")
    p.add_argument("--va-min-amount", type=float, default=10.0, help="价值平均最低申购 (默认 10)")
    p.add_argument("--end", default=None, help="回测终点 (默认今天)")
    p.add_argument("--output", default=None, help="输出 Markdown 文件路径 (默认 stdout)")
    return p.parse_args()


def _parse_scenarios(raw: str) -> list[tuple[str, str]]:
    """解析 '熊市底部:2019-01-10,牛市顶部:2021-07-09' → [(名称, 日期), ...]"""
    result = []
    for item in raw.split(","):
        item = item.strip()
        if ":" not in item:
            raise ValueError(f"场景格式错误，应为 '名称:日期'，收到: {item}")
        name, date = item.rsplit(":", 1)
        result.append((name.strip(), date.strip()))
    return result


def load_ma_buffer(fund_code: str, start_date: str, buffer_days: int = 500) -> pd.DataFrame | None:
    """从缓存读取 start_date 之前的数据用于均线计算"""
    ma_start = (pd.Timestamp(start_date) - pd.Timedelta(days=buffer_days)).strftime("%Y-%m-%d")
    try:
        extra = db.fund_nav_history.load(fund_code, ma_start, start_date)
        if extra is not None and not extra.empty:
            extra["date"] = pd.to_datetime(extra["净值日期"])
            extra["unit_nav"] = pd.to_numeric(extra["单位净值"], errors="coerce")
            extra["acc_nav"] = pd.to_numeric(extra["累计净值"], errors="coerce")
            extra["daily_return"] = pd.to_numeric(extra["日增长率"], errors="coerce")
            return extra
    except Exception:
        pass
    return None


def run_backtest(fund_code: str, start: str, end: str, amount: float, fee: float,
                 freq: str, strategy: str,
                 ma_period: int = 250,
                 va_target: float = 1000,
                 va_max_multiple: float = 4.0,
                 va_min_amount: float = 10.0) -> dict:
    """运行单个回测，返回指标字典"""
    nav_df = fetch_fund_data(fund_code, start, end)
    dividend_df = fetch_dividend_data(fund_code)
    invest_dates = generate_dca_dates(nav_df, freq, start, end)

    if strategy == "fixed":
        buy = FixedBuyStrategy(amount, fee)
    elif strategy == "va":
        buy = ValueAveragingBuyStrategy(va_target, va_max_multiple, va_min_amount, fee)
    elif strategy == "ma":
        extra = load_ma_buffer(fund_code, start)
        if extra is not None:
            ma_nav = pd.concat([extra, nav_df], ignore_index=True)
            ma_nav = ma_nav.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
        else:
            ma_nav = nav_df
        buy = MovingAverageBuyStrategy(amount, ma_period, fee, ma_nav)

    detail, events, redeem_fee, final_val = simulate_dca(nav_df, invest_dates, buy,
                                                          dividend_df=dividend_df)
    total_invest = detail.iloc[-1]["total_invested"]
    total_ret = (final_val - total_invest) / total_invest
    ann_ret = calc_annualized(total_ret, pd.Timestamp(start), pd.Timestamp(end))
    mdd = max_drawdown(detail["total_value"])
    return dict(total_invest=total_invest, final_val=final_val,
                total_ret=total_ret, ann_ret=ann_ret, mdd=mdd)


def run_lumpsum(fund_code: str, start: str, end: str, amount: float, fee: float) -> dict | None:
    """运行一次性投资对照"""
    nav_df = fetch_fund_data(fund_code, start, end)
    dividend_df = fetch_dividend_data(fund_code)
    result = calc_lumpsum(nav_df, amount, start, end, fee, dividend_df=dividend_df)
    if result:
        ls_ret = result["return_rate"]
        ann_ret = calc_annualized(ls_ret, pd.Timestamp(start), pd.Timestamp(end))
        return dict(amount=amount, final_val=result["value_after_fee"],
                    total_ret=ls_ret, ann_ret=ann_ret, mdd=0.0)
    return None


def fmt_pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def fmt_money(v: float) -> str:
    return f"{v:,.0f}"


def fmt_ann(v: float) -> str:
    return f"{v * 100:.2f}%"


def build_markdown_table(records: list[dict], fund_names: dict[str, str]) -> str:
    """将回测结果组装为 Markdown 表格输出"""
    lines = [
        "# 定投策略对比报告\n",
        f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n",
    ]

    # ── 按基金分组输出 ──
    for fund_code in sorted({r["fund_code"] for r in records}):
        fund_name = fund_names.get(fund_code, fund_code)
        lines.append(f"## {fund_code} {fund_name}\n")
        lines.append("```")
        header = f"{'起点':>10}  {'定期定额':>24}  {'价值平均':>24}  {'指数均线':>24}  {'一次性投资':>24}"
        lines.append(header)
        lines.append("─" * len(header))

        fund_records = [r for r in records if r["fund_code"] == fund_code]
        for sr in sorted(
            (r for r in fund_records if r["strategy"] == "fixed"),
            key=lambda x: x["start_date"],
        ):
            scenario_name = sr["scenario_name"]
            start = sr["start_date"]
            fixed = sr
            va = next(
                (r for r in fund_records if r["strategy"] == "va" and r["start_date"] == start),
                None,
            )
            ma = next(
                (r for r in fund_records if r["strategy"] == "ma" and r["start_date"] == start),
                None,
            )
            ls = next(
                (r for r in fund_records if r["strategy"] == "lumpsum" and r["start_date"] == start),
                None,
            )

            def cell(r: dict | None, show_mdd: bool = True) -> str:
                if r is None:
                    return "—"
                ret_str = f"{fmt_pct(r['total_ret'])} / {fmt_ann(r['ann_ret'])}"
                if show_mdd:
                    return f"{ret_str}  回撤 {fmt_pct(r['mdd'])}  投入 {fmt_money(r['total_invest'])}"
                return f"{ret_str}  投入 {fmt_money(r['total_invest'])}"

            lines.append(
                f"{scenario_name:>10}  {cell(fixed):>24}  {cell(va):>24}  {cell(ma):>24}  {cell(ls, False):>24}"
            )

        lines.append("```\n")

    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    end_date = args.end or datetime.today().strftime("%Y-%m-%d")
    fund_codes = [c.strip() for c in args.funds.split(",")]

    # ── 场景来源：手动指定 或 自动寻找 ──
    if args.auto_scenarios:
        specs = _parse_scenarios(args.scenarios_spec)
        scenarios = find_scenarios(args.auto_scenarios, specs)
        print(f"自动识别场景: {', '.join(f'{n}({d})' for n, d in scenarios)}", file=sys.stderr)
    elif args.scenarios:
        scenarios = _parse_scenarios(args.scenarios)
    else:
        print("错误: 必须指定 --scenarios 或 --auto-scenarios", file=sys.stderr)
        sys.exit(1)

    # 预读基金名称
    db.init_db()
    cat = db.fund_catalog.load()
    fund_names: dict[str, str] = {}
    if cat is not None:
        for code in fund_codes:
            r = cat[cat["基金代码"] == code]
            if not r.empty:
                fund_names[code] = r.iloc[0]["基金简称"]

    strategies = [
        ("fixed", "定期定额"),
        ("va", "价值平均"),
        ("ma", "指数均线"),
        ("lumpsum", "一次性投资"),
    ]

    records: list[dict] = []

    for fund_code in fund_codes:
        for scenario_name, start in scenarios:
            try:
                ref = run_backtest(
                    fund_code, start, end_date, args.amount, args.fee, args.freq, "fixed",
                    ma_period=args.ma_period,
                    va_target=args.va_target,
                    va_max_multiple=args.va_max_multiple,
                    va_min_amount=args.va_min_amount,
                )
            except BacktestError as e:
                print(f"跳过 {fund_code} {scenario_name}({start}): {e}", file=sys.stderr)
                continue

            lumpsum_amount = ref["total_invest"]

            for sname, _ in strategies:
                if sname == "lumpsum":
                    ls = run_lumpsum(fund_code, start, end_date, lumpsum_amount, args.fee)
                    if ls:
                        records.append(dict(
                            fund_code=fund_code, scenario_name=scenario_name,
                            start_date=start, strategy="lumpsum",
                            total_invest=lumpsum_amount, **ls,
                        ))
                else:
                    try:
                        r = run_backtest(
                            fund_code, start, end_date, args.amount, args.fee, args.freq, sname,
                            ma_period=args.ma_period,
                            va_target=args.va_target,
                            va_max_multiple=args.va_max_multiple,
                            va_min_amount=args.va_min_amount,
                        )
                    except BacktestError as e:
                        print(f"跳过 {fund_code} {scenario_name} {sname}: {e}", file=sys.stderr)
                        continue
                    records.append(dict(
                        fund_code=fund_code, scenario_name=scenario_name,
                        start_date=start, strategy=sname, **r,
                    ))

    if not records:
        print("无有效回测结果", file=sys.stderr)
        sys.exit(1)

    output = build_markdown_table(records, fund_names)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"报告已写入: {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
