"""
定投回测核心引擎：数据加载、分红处理、模拟循环、一次性投入对照
供 app_pages/dca.py, tools/compare_strategies.py, tests/ 及 CLI 调用
"""

import akshare as ak
import pandas as pd
import db
from datetime import timedelta
from typing import Any, TypedDict

from backend.em_fetcher import fetch_nav_data
from backend.logger import get_logger
from backend.parse_utils import normalize_nav_df
from backend.strategy import BuyStrategy, DCAPosition, SellStrategy

logger = get_logger(__name__)


class BacktestError(Exception):
    """定投回测过程中的错误"""


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
    daily_detail: pd.DataFrame


def fetch_fund_data(fund_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """获取基金历史净值数据（单位净值 + 累计净值），优先从本地缓存读取"""
    db.init_db()
    if db.fund_nav_history.is_cached(fund_code, end_date):
        cached = db.fund_nav_history.load(fund_code, start_date, end_date)
        if cached is not None and not cached.empty:
            logger.info("从本地缓存读取 %d 条净值记录", len(cached))
            df = cached
            return normalize_nav_df(df)

    logger.info("获取基金 %s 历史净值数据 ...", fund_code)
    try:
        df = fetch_nav_data(fund_code)
    except Exception as e:
        raise BacktestError(f"获取数据失败: {e}")

    if df.empty:
        raise BacktestError("未获取到数据，请检查基金代码是否正确")

    db.fund_nav_history.save(fund_code, df)

    df = normalize_nav_df(df)

    mask = (df["date"] >= pd.Timestamp(start_date)) & (df["date"] <= pd.Timestamp(end_date))
    df = df[mask].reset_index(drop=True)

    if df.empty:
        raise BacktestError(f"{start_date} ~ {end_date} 范围内无数据")

    logger.info("获取到 %d 条净值记录", len(df))
    return df


def fetch_dividend_data(fund_code: str) -> pd.DataFrame:
    """获取基金真实分红事件，缓存优先 → 天天基金网 API 兜底"""
    db.init_db()
    cached = db.fund_dividend.load(fund_code)
    if cached is not None:
        cached["除息日"] = pd.to_datetime(cached["除息日"])
        return cached
    try:
        df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="分红送配详情", period="成立来")
    except Exception:
        logger.warning("获取分红数据失败: %s", fund_code)
        return pd.DataFrame()
    if df is None or df.empty or "暂无" in str(df.iloc[0, 0]):
        return pd.DataFrame()
    df["每份分红"] = df["每份分红"].str.extract(r"([\d.]+)").astype(float)
    df["除息日"] = pd.to_datetime(df["除息日"])
    result = df[["除息日", "每份分红"]].sort_values("除息日").reset_index(drop=True)
    db.fund_dividend.save(fund_code, result)
    return result


def fetch_fund_name(fund_code: str) -> str:
    """获取基金简称"""
    df = db.fund_catalog.load()
    if df is not None:
        row = df[df["基金代码"] == fund_code]
        if not row.empty:
            return row.iloc[0]["基金简称"]
    return fund_code


def generate_dca_dates(
    nav_df: pd.DataFrame, freq: str, start_date: str, end_date: str, day: int = 10, weekday: int = 1
) -> pd.DatetimeIndex:
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
    units: float,
    nav: float,
    date: pd.Timestamp,
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


def _execute_sell(
    pos: DCAPosition,
    date: pd.Timestamp,
    nav: float,
    mkt_value: float,
    round_return: float,
    sell_reason: str,
    redeem_schedule: list[tuple[int, float]] | None,
    tp_cycle: bool,
    sell_strategy: SellStrategy,
    buy_strategy: BuyStrategy,
) -> dict[str, Any]:
    """执行卖出：计算赎回费、重置持仓、返回事件记录"""
    fee = calc_redeem_fee(pos.fee_batches, date, nav, redeem_schedule)
    net = mkt_value - fee
    event = {
        "date": date,
        "nav": nav,
        "return_rate": round_return,
        "round_cost": pos.cost,
        "profit": mkt_value - pos.cost,
        "redeem_fee": fee,
        "net_proceeds": net,
        "reason": sell_reason,
    }
    pos.total_recovered += net
    pos.units = 0.0
    pos.cost = 0.0
    pos.peak_return = -INF
    pos.fee_batches = []
    pos.is_active = tp_cycle
    sell_strategy.on_reset()
    buy_strategy.on_reset()
    return event


def _build_record(
    date: pd.Timestamp,
    nav: float,
    inv_today: float,
    unit_added: float,
    div_units: float,
    pos: DCAPosition,
    mkt_value: float,
    deviation: float | None = None,
    multiplier: float | None = None,
) -> dict[str, Any]:
    """构建单日快照记录"""
    total_value = mkt_value + pos.total_recovered
    overall_profit = total_value - pos.total_invested
    overall_return = overall_profit / pos.total_invested if pos.total_invested > 0 else 0.0
    rec: dict[str, Any] = {
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
    }
    if deviation is not None:
        rec["deviation"] = deviation
        rec["multiplier"] = multiplier
    return rec


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
    nav_dict = nav_df.set_index("date")["unit_nav"].to_dict()
    dividend_dict = build_dividend_dict(dividend_df)

    stop_profit_on = sell_strategy is not None
    invest_set = set(invest_dates)
    pos = DCAPosition()
    records: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    for date in nav_df["date"]:
        nav = nav_dict[date]
        inv_today = unit_added = div_units = 0.0

        div_units = reinvest_dividends(pos.units, nav, date, dividend_dict)
        if div_units > 0:
            pos.units += div_units

        action = buy_strategy.should_buy(date, nav, pos, invest_set)
        if action.amount > 0:
            net = action.amount * (1 - action.fee_rate)
            unit_added = net / nav
            pos.units += unit_added
            pos.cost += action.amount
            pos.total_invested += action.amount
            inv_today = action.amount
            pos.fee_batches.append({"date": date, "units": unit_added})

        deviation = action.deviation
        multiplier = action.multiplier

        if pos.units > 0:
            mkt_value = pos.units * nav
            round_return = (mkt_value - pos.cost) / pos.cost
        else:
            mkt_value = round_return = 0.0
        if pos.units > 0 and round_return > pos.peak_return:
            pos.peak_return = round_return

        should_sell = False
        sell_reason = ""
        if sell_strategy is not None:
            signal = sell_strategy.evaluate(date, nav, pos, mkt_value, round_return)
            if signal.stop_buying:
                pos.is_active = False
            if signal.should_sell:
                should_sell = True
                sell_reason = signal.reason

        if should_sell and sell_strategy is not None:
            event = _execute_sell(
                pos,
                date,
                nav,
                mkt_value,
                round_return,
                sell_reason,
                redeem_schedule,
                tp_cycle,
                sell_strategy,
                buy_strategy,
            )
            events.append(event)
            mkt_value = round_return = 0.0

        if stop_profit_on or date in invest_set or div_units > 0:
            records.append(
                _build_record(date, nav, inv_today, unit_added, div_units, pos, mkt_value, deviation, multiplier)
            )

    detail = pd.DataFrame(records)
    if detail.empty:
        raise BacktestError("未生成有效的定投记录")

    final_redeem_fee = 0.0
    if pos.units > 0 and pos.fee_batches:
        last_row = detail.iloc[-1]
        final_redeem_fee = calc_redeem_fee(pos.fee_batches, last_row["date"], last_row["nav"], redeem_schedule)

    last_market_value = detail.iloc[-1]["market_value"]
    final_value = pos.total_recovered + (last_market_value - final_redeem_fee)
    return detail, events, final_redeem_fee, final_value


def calc_lumpsum(
    nav_df: pd.DataFrame,
    amount: float,
    start_date: str,
    end_date: str,
    purchase_rate: float,
    redeem_schedule: list[tuple[int, float]] | None = None,
    dividend_df: pd.DataFrame | None = None,
) -> dict[str, Any] | None:
    """一次性投入收益计算（基于真实分红数据再投资）"""
    df = nav_df.loc[nav_df["date"] >= pd.Timestamp(start_date)].reset_index(drop=True)
    if df.empty:
        return None

    first = df.iloc[0]
    actual = amount * (1 - purchase_rate)
    units = actual / first["unit_nav"]
    dividend_dict = build_dividend_dict(dividend_df)

    daily_records: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        units += reinvest_dividends(units, row["unit_nav"], row["date"], dividend_dict)
        daily_value = units * row["unit_nav"]
        daily_return = (daily_value - amount) / amount
        daily_records.append(
            {"date": row["date"], "total_value": daily_value, "total_invested": amount, "return_rate": daily_return}
        )

    daily_detail = pd.DataFrame(daily_records)
    last = daily_detail.iloc[-1]
    val_before = last["total_value"]
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
        "daily_detail": daily_detail,
    }


def load_ma_buffer(
    fund_code: str,
    start_date: str,
    ma_period: int,
    nav_df: pd.DataFrame,
) -> pd.DataFrame:
    """加载 start_date 前的净值预热，合并入 nav_df 用于均线计算"""
    ma_start = (pd.Timestamp(start_date) - pd.Timedelta(days=ma_period * 2)).strftime("%Y-%m-%d")
    try:
        extra = db.fund_nav_history.load(fund_code, ma_start, start_date)
        if extra is not None and not extra.empty:
            extra = normalize_nav_df(extra)
            ma_nav = pd.concat([extra, nav_df], ignore_index=True)
            return ma_nav.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
    except Exception:
        logger.warning("MA warmup 加载失败，回退基金净值: %s", fund_code)
    return nav_df
