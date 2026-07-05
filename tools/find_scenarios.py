"""
根据基金净值历史自动寻找关键市场位置（牛市顶部/熊市底部/市场平均）

输出格式与 compare_strategies.py 的 --scenarios 参数兼容，可直接管道使用:

  uv run python -m tools.find_scenarios --fund 110026 --scenarios "牛市顶部:2021,熊市底部:2018-2019,市场平均:2020"

场景类型说明:
  牛市顶部:YYYY        — 指定年份内净值最高日
  熊市底部:YYYY-YYYY   — 指定日期区间内净值最低日
  市场平均:YYYY        — 指定年份内净值最接近中位数的日
"""

import argparse
import sys

import pandas as pd

import db
from backend.em_fetcher import fetch_nav_data


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="自动寻找基金关键市场位置")
    p.add_argument("--fund", required=True, help="基金代码")
    p.add_argument(
        "--scenarios",
        required=True,
        help='场景规格，逗号分隔，如 "牛市顶部:2021,熊市底部:2018-2019,市场平均:2020"',
    )
    return p.parse_args()


def _load_full_nav(fund_code: str) -> pd.DataFrame:
    """加载基金全量净值数据（缓存优先）"""
    db.init_db()
    if db.fund_nav_history.is_cached(fund_code, "2099-12-31"):
        raw = db.fund_nav_history.load(fund_code, "2000-01-01", "2099-12-31")
        if raw is not None and not raw.empty:
            raw["date"] = pd.to_datetime(raw["净值日期"])
            raw["unit_nav"] = pd.to_numeric(raw["单位净值"], errors="coerce")
            return raw[["date", "unit_nav"]].dropna()

    # 缓存不足 → 从 API 获取并缓存
    df = fetch_nav_data(fund_code)
    db.fund_nav_history.save(fund_code, df)
    df["date"] = pd.to_datetime(df["净值日期"])
    df["unit_nav"] = pd.to_numeric(df["单位净值"], errors="coerce")
    return df[["date", "unit_nav"]].dropna()


def _find_bull_top(df: pd.DataFrame, year: str) -> str:
    """牛市顶部：指定年份内净值最高日"""
    sub = df[df["date"].dt.year == int(year)]
    if sub.empty:
        raise ValueError(f"{year} 年无数据")
    row = sub.loc[sub["unit_nav"].idxmax()]
    return row["date"].strftime("%Y-%m-%d")


def _find_bear_bottom(df: pd.DataFrame, year_range: str) -> str:
    """熊市底部：指定日期区间内净值最低日"""
    parts = year_range.split("-")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        raise ValueError(f"熊市底部格式应为 YYYY-YYYY，收到: {year_range}")
    start = f"{parts[0]}-01-01"
    end = f"{parts[1]}-12-31"
    sub = df[(df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))]
    if sub.empty:
        raise ValueError(f"{start} ~ {end} 范围内无数据")
    row = sub.loc[sub["unit_nav"].idxmin()]
    return row["date"].strftime("%Y-%m-%d")


def _find_average(df: pd.DataFrame, year: str) -> str:
    """市场平均：指定年份内净值最接近中位数的日"""
    sub = df[df["date"].dt.year == int(year)]
    if sub.empty:
        raise ValueError(f"{year} 年无数据")
    median = sub["unit_nav"].median()
    row = sub.loc[(sub["unit_nav"] - median).abs().idxmin()]
    return row["date"].strftime("%Y-%m-%d")


SCENARIO_HANDLERS = {
    "牛市顶部": _find_bull_top,
    "熊市底部": _find_bear_bottom,
    "市场平均": _find_average,
}


def find_scenarios(fund_code: str, specs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """执行场景查找，返回 [(名称, YYYY-MM-DD), ...]"""
    df = _load_full_nav(fund_code)
    results: list[tuple[str, str]] = []
    for name, arg in specs:
        handler = SCENARIO_HANDLERS.get(name)
        if handler is None:
            raise ValueError(f"不支持的场景类型: {name}（支持: {', '.join(SCENARIO_HANDLERS)}）")
        date_str = handler(df, arg)
        results.append((name, date_str))
    return results


def main() -> None:
    args = parse_args()

    # 解析场景规格
    specs: list[tuple[str, str]] = []
    for item in args.scenarios.split(","):
        item = item.strip()
        if ":" not in item:
            print(f"格式错误: {item}，应如 名称:参数", file=sys.stderr)
            sys.exit(1)
        name, param = item.rsplit(":", 1)
        specs.append((name.strip(), param.strip()))

    try:
        results = find_scenarios(args.fund, specs)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)

    # 输出 compare_strategies.py 兼容格式
    out = ",".join(f"{name}:{date}" for name, date in results)
    print(out)


if __name__ == "__main__":
    main()
