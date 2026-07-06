"""simulate_dca 核心回测逻辑 + 辅助函数集成测试

测试策略：
- mock NAV 数据（无网络依赖）
- 从已知输入手动推导预期输出
- 覆盖三策略 + 分红 + 止盈 + 赎回费
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from backend.dca_backtest import (
    build_dividend_dict,
    calc_lumpsum,
    calc_redeem_fee,
    fetch_dividend_data,
    generate_dca_dates,
    reinvest_dividends,
    simulate_dca,
)
from backend.strategy import (
    FixedBuyStrategy,
    MovingAverageBuyStrategy,
    TargetProfitSellStrategy,
    TrailingStopSellStrategy,
    ValueAveragingBuyStrategy,
)


def _nav_df(unit_navs: list[float], acc_navs: list[float] | None = None) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=len(unit_navs), freq="D")
    if acc_navs is None:
        acc_navs = unit_navs
    return pd.DataFrame(
        {
            "date": dates,
            "unit_nav": unit_navs,
            "acc_nav": acc_navs,
            "daily_return": [0.0] * len(unit_navs),
        }
    )


# =============================================================================
# simulate_dca 集成测试
# =============================================================================


class TestSimulateDCABasic:
    """定期定额 + 基础场景"""

    def test_fixed_buy_flat_nav(self) -> None:
        """净值不变：3 次买入 → 份额准确，赎回费按持有天数阶梯计算"""
        nav = _nav_df([1.0] * 5)
        dates = pd.DatetimeIndex([nav["date"].iloc[0], nav["date"].iloc[2], nav["date"].iloc[4]])
        buy = FixedBuyStrategy(1000, 0.0015)
        detail, events, fee, final_val = simulate_dca(nav, dates, buy)

        assert len(events) == 0
        assert len(detail) == 3
        assert detail.iloc[-1]["total_invested"] == 3000
        net = 1000 * (1 - 0.0015)
        assert detail.iloc[-1]["total_units"] == pytest.approx(3 * net / 1.0)
        assert detail.iloc[-1]["return_rate"] == pytest.approx(-0.0015)

        # 三批：持有天数 4 / 2 / 0，末批 0 天不产生赎回费
        fee_per_batch = net * 1.0 * 0.015
        assert fee == pytest.approx(2 * fee_per_batch)

    def test_fixed_buy_rising_nav(self) -> None:
        """净值上涨：产生正收益，赎回费正确"""
        nav = _nav_df([1.0, 1.0, 2.0, 2.0, 2.0])
        dates = pd.DatetimeIndex([nav["date"].iloc[0], nav["date"].iloc[2]])
        buy = FixedBuyStrategy(1000, 0.0015)
        detail, events, fee, final_val = simulate_dca(nav, dates, buy)

        net = 1000 * (1 - 0.0015)
        units1 = net / 1.0
        units2 = net / 2.0
        total_units = units1 + units2

        assert detail.iloc[-1]["total_units"] == pytest.approx(total_units)
        mkt_val = total_units * 2.0
        assert detail.iloc[-1]["market_value"] == pytest.approx(mkt_val)

        # 赎回费：末批持有 0 天免赎回费
        f1 = units1 * 2.0 * 0.015
        assert fee == pytest.approx(f1)

    def test_rising_nav_generates_profit(self) -> None:
        """净值上涨 → 最终市值 > 总投入（确保基础盈利场景通过）"""
        nav = _nav_df([1.0, 1.0, 1.5, 1.5, 2.0])
        dates = pd.DatetimeIndex([nav["date"].iloc[0], nav["date"].iloc[2], nav["date"].iloc[4]])
        buy = FixedBuyStrategy(1000, 0.0015)
        detail, events, fee, final_val = simulate_dca(nav, dates, buy)

        total_inv = detail.iloc[-1]["total_invested"]
        assert final_val > total_inv  # 净值上涨→盈利


class TestSimulateDCADividend:
    """分红再投资"""

    def test_dividend_adds_units(self) -> None:
        """分红日增加份额"""
        nav = _nav_df([1.0] * 5)
        dates = pd.DatetimeIndex([nav["date"].iloc[0]])
        buy = FixedBuyStrategy(1000, 0.0015)
        div_df = pd.DataFrame({"除息日": [nav["date"].iloc[2]], "每份分红": [0.1]})

        detail, events, fee, final_val = simulate_dca(nav, dates, buy, dividend_df=div_df)

        net = 1000 * (1 - 0.0015)
        # 第一天买入 998.5 份，第三天分红再投 +99.85 份
        assert detail.iloc[-1]["total_units"] == pytest.approx(net + net * 0.1 / 1.0)

    def test_dividend_before_first_buy_skipped(self) -> None:
        """分红日在首次买入之前 → 不处理（无持仓）"""
        nav = _nav_df([1.0] * 5)
        dates = pd.DatetimeIndex([nav["date"].iloc[3]])
        buy = FixedBuyStrategy(1000, 0.0015)
        div_df = pd.DataFrame({"除息日": [nav["date"].iloc[0]], "每份分红": [0.1]})

        detail, events, fee, final_val = simulate_dca(nav, dates, buy, dividend_df=div_df)

        net = 1000 * (1 - 0.0015)
        div_units = detail["dividend_units"].sum()
        assert div_units == 0.0
        assert detail.iloc[-1]["total_units"] == pytest.approx(net / 1.0)

    def test_dividend_recorded_in_detail(self) -> None:
        """分红日出现在 detail 中（没有 invest_set 日也有记录）"""
        nav = _nav_df([1.0] * 5)
        dates = pd.DatetimeIndex([nav["date"].iloc[0]])
        buy = FixedBuyStrategy(1000, 0.0015)
        div_df = pd.DataFrame({"除息日": [nav["date"].iloc[2]], "每份分红": [0.05]})

        detail, events, fee, final_val = simulate_dca(nav, dates, buy, dividend_df=div_df)

        # 应有 2 条记录：买入日 + 分红日
        assert len(detail) >= 2
        div_row = detail[detail["dividend_units"] > 0]
        assert len(div_row) == 1


class TestSimulateDCASell:
    """止盈卖出"""

    def test_target_profit_triggered(self) -> None:
        """目标止盈 20%，净值从 1.0 涨到 1.3 触发卖出"""
        nav = _nav_df([1.0, 1.1, 1.2, 1.3])
        dates = pd.DatetimeIndex([nav["date"].iloc[0]])
        buy = FixedBuyStrategy(1000, 0.0015)
        sell = TargetProfitSellStrategy(0.20)

        detail, events, fee, final_val = simulate_dca(nav, dates, buy, sell_strategy=sell)

        assert len(events) == 1
        assert events[0]["reason"].startswith("目标收益率")

    def test_target_profit_not_triggered_below_threshold(self) -> None:
        """净值涨幅未达阈值 → 不触发卖出"""
        nav = _nav_df([1.0, 1.1, 1.15])
        dates = pd.DatetimeIndex([nav["date"].iloc[0]])
        buy = FixedBuyStrategy(1000, 0.0015)
        sell = TargetProfitSellStrategy(0.20)

        detail, events, fee, final_val = simulate_dca(nav, dates, buy, sell_strategy=sell)

        assert len(events) == 0

    def test_tp_cycle_reinvest_after_sell(self) -> None:
        """止盈循环：卖出后清仓，下一个投资日重新开始定投"""
        nav = _nav_df([1.0, 1.1, 1.3, 0.9, 0.9, 1.0])
        dates = pd.DatetimeIndex([nav["date"].iloc[0], nav["date"].iloc[3], nav["date"].iloc[5]])
        buy = FixedBuyStrategy(1000, 0.0015)
        sell = TargetProfitSellStrategy(0.20)

        detail, events, fee, final_val = simulate_dca(nav, dates, buy, sell_strategy=sell, tp_cycle=True)

        assert len(events) == 1  # 第3天止盈
        # 卖出后 tp_cycle=True → is_active=True，第4天继续买入
        assert detail.iloc[-1]["total_invested"] > 1000  # 不止一期投入

    def test_trailing_stop_flow(self) -> None:
        """移动止盈：收益达阈值停投 → 回撤触发卖出"""
        nav = _nav_df([1.0, 1.1, 1.3, 1.3, 1.3, 1.15])
        dates = pd.DatetimeIndex([nav["date"].iloc[0]])
        buy = FixedBuyStrategy(1000, 0.0015)
        sell = TrailingStopSellStrategy(0.20, 0.08)

        detail, events, fee, final_val = simulate_dca(nav, dates, buy, sell_strategy=sell)

        assert len(events) == 1  # 回撤 8% 触发卖出
        # 停投后 is_active=False，第2天（1.1）不触发（0.10 < 0.20），
        # 第3天（1.3）触发 stop_buying=True → is_active=False
        # 第6天（1.15）回撤 11.5% > 8% → 卖出

    def test_no_sell_events_when_no_sell_strategy(self) -> None:
        """无止盈策略 → events 为空列表"""
        nav = _nav_df([1.0, 2.0])
        dates = pd.DatetimeIndex([nav["date"].iloc[0]])
        buy = FixedBuyStrategy(1000, 0.0015)

        detail, events, fee, final_val = simulate_dca(nav, dates, buy)

        assert len(events) == 0
        assert final_val > 0


class TestSimulateDCAValueAveraging:
    """价值平均策略集成"""

    def test_va_invests_more_on_dip(self) -> None:
        """净值下跌 → VA 投入更多（低于目标值）"""
        # 第一期 NAV=1.0, 目标市值=1000, 投入 1000（满额）
        # 第二期 NAV=0.8, 第一期持仓现价 = 998.5 * 0.8 = 798.8
        # 目标市值=2000, 需投入=2000-798.8=1201.2
        nav = _nav_df([1.0, 0.8])
        dates = pd.DatetimeIndex([nav["date"].iloc[0], nav["date"].iloc[1]])
        va = ValueAveragingBuyStrategy(1000, 4.0, 10, 0.0015)

        detail, events, fee, final_val = simulate_dca(nav, dates, va)

        assert detail.iloc[1]["investment"] > 1000  # 下跌 → 多投

    def test_va_invests_less_on_rise(self) -> None:
        """净值上涨 → VA 投入更少（低于目标值但 > 0 → 投 required 整额）"""
        # 第一期 NAV=1.0, 目标市值=1000, 投入 1000（满额）
        # 第二期 NAV=2.0, 第一期持仓现价 = 998.5 * 2.0 = 1997.0
        # 目标市值=2000, 需投入=2000-1997=3.0 → math.ceil(300)/100 = 3.0
        nav = _nav_df([1.0, 2.0])
        dates = pd.DatetimeIndex([nav["date"].iloc[0], nav["date"].iloc[1]])
        va = ValueAveragingBuyStrategy(1000, 4.0, 10, 0.0015)

        detail, events, fee, final_val = simulate_dca(nav, dates, va)

        assert detail.iloc[1]["investment"] == 3.0


class TestSimulateDCAMovingAverage:
    """均线策略集成"""

    def test_ma_aggressive_oversold(self) -> None:
        """超卖（偏离 < -15%）→ 3x 买入"""
        vals = [1.0] * 300 + [0.84]
        nav = _nav_df(vals)
        dates = pd.DatetimeIndex([nav["date"].iloc[-1]])
        tiers, mults = MovingAverageBuyStrategy.MA_MODES["aggressive"]
        ma = MovingAverageBuyStrategy(1000, 250, 0.0015, nav, tiers, mults)

        detail, events, fee, final_val = simulate_dca(nav, dates, ma)

        # 偏离度 = (0.84 - 1.0) / 1.0 = -0.16 < -0.15 → 3x
        assert detail.iloc[0]["investment"] == pytest.approx(3000)

    def test_ma_slight_undervalue_base_amount(self) -> None:
        """微低估（偏离 -3%）→ 1x 买入（default 模式 -5%~0 区间）"""
        vals = [1.0] * 300 + [0.97]
        nav = _nav_df(vals)
        dates = pd.DatetimeIndex([nav["date"].iloc[-1]])
        tiers, mults = MovingAverageBuyStrategy.MA_MODES["default"]
        ma = MovingAverageBuyStrategy(1000, 250, 0.0015, nav, tiers, mults)

        detail, events, fee, final_val = simulate_dca(nav, dates, ma)

        assert detail.iloc[0]["investment"] == pytest.approx(1000)


# =============================================================================
# calc_lumpsum 测试
# =============================================================================


class TestCalcLumpsum:
    def test_basic_no_dividend(self) -> None:
        """一次性投入：净值从 1.0 涨到 2.0，无分红"""
        nav = _nav_df([1.0, 1.5, 2.0])
        result = calc_lumpsum(nav, 10000, "2024-01-01", "2024-01-03", 0.0015)

        assert result is not None
        net = 10000 * (1 - 0.0015)
        units = net / 1.0
        val_before = units * 2.0
        # 持有 2 天 < 7 天 → 1.5%
        fee = val_before * 0.015
        val_after = val_before - fee
        ret = (val_after - 10000) / 10000
        assert result["return_rate"] == pytest.approx(ret)

    def test_with_dividends(self) -> None:
        """一次性投入 + 分红再投资"""
        nav = _nav_df([1.0, 1.0, 1.0])
        div_df = pd.DataFrame({"除息日": [nav["date"].iloc[1]], "每份分红": [0.1]})
        result = calc_lumpsum(nav, 10000, "2024-01-01", "2024-01-03", 0.0015, dividend_df=div_df)

        assert result is not None
        net = 10000 * (1 - 0.0015)
        units = net / 1.0
        units += units * 0.1 / 1.0  # 分红再投
        val_before = units * 1.0
        fee = val_before * 0.015
        val_after = val_before - fee
        ret = (val_after - 10000) / 10000
        assert result["return_rate"] == pytest.approx(ret)

    def test_no_dividend_df_none(self) -> None:
        """dividend_df=None → 等同于空分红"""
        nav = _nav_df([1.0, 2.0])
        result = calc_lumpsum(nav, 10000, "2024-01-01", "2024-01-02", 0.0015)
        result_none = calc_lumpsum(nav, 10000, "2024-01-01", "2024-01-02", 0.0015, dividend_df=None)
        assert result is not None and result_none is not None
        assert result["return_rate"] == result_none["return_rate"]

    def test_no_data_in_range(self) -> None:
        """start_date 超出数据范围 → 返回 None"""
        nav = _nav_df([1.0, 1.0])
        result = calc_lumpsum(nav, 10000, "2025-01-01", "2025-01-02", 0.0015)
        assert result is None


# =============================================================================
# generate_dca_dates 测试
# =============================================================================


class TestGenerateDCADates:
    def test_monthly_on_trading_days(self) -> None:
        """每月 10 号，10 号是交易日 → 返回 10 号"""
        nav = _nav_df([1.0] * 31)
        # 2024-01 有 31 天，10 号是星期三（交易日）
        dates = generate_dca_dates(nav, "monthly", "2024-01-01", "2024-01-31", day=10)
        assert len(dates) == 1
        assert dates[0].day == 10

    def test_monthly_forward_walk(self) -> None:
        """每月 1 号，1 号是假期 → 向前找到最近交易日"""
        # 2024-01-01 是元旦（非交易日），用 2024-01-02
        # 需要构造有 2024-01-02 的 nav_df
        dates_list = pd.date_range("2024-01-02", periods=30, freq="D")
        df = pd.DataFrame(
            {
                "date": dates_list,
                "unit_nav": [1.0] * 30,
                "acc_nav": [1.0] * 30,
                "daily_return": [0.0] * 30,
            }
        )
        result = generate_dca_dates(df, "monthly", "2024-01-01", "2024-01-31", day=1)
        assert len(result) == 1
        assert result[0] == pd.Timestamp("2024-01-02")

    def test_daily_returns_all_trading_days(self) -> None:
        """daily 频率 → 返回所有交易日"""
        nav = _nav_df([1.0] * 10)
        dates = generate_dca_dates(nav, "daily", "2024-01-01", "2024-01-10")
        assert len(dates) == 10

    def test_weekly_returns_weekdays(self) -> None:
        """weekly 频率 → 返回指定周几"""
        nav = _nav_df([1.0] * 14)  # 14 天覆盖两周
        dates = generate_dca_dates(nav, "weekly", "2024-01-01", "2024-01-14", weekday=1)
        assert len(dates) == 2
        # 1 = 周一，2024-01-01 是周一
        assert dates[0].weekday() == 0  # 0 = Monday in Python

    def test_forward_walk_10_day_limit(self) -> None:
        """向前 10 天仍无交易日 → 跳过"""
        dates_list = pd.date_range("2024-01-15", periods=5, freq="D")
        df = pd.DataFrame(
            {
                "date": dates_list,
                "unit_nav": [1.0] * 5,
                "acc_nav": [1.0] * 5,
                "daily_return": [0.0] * 5,
            }
        )
        # 候选日 2024-01-01，向前走 10 天到 2024-01-11，仍不在 nav 中 → 跳过
        result = generate_dca_dates(df, "monthly", "2024-01-01", "2024-01-20", day=1)
        assert len(result) == 0


# =============================================================================
# reinvest_dividends 测试
# =============================================================================


class TestReinvestDividends:
    def test_basic_reinvestment(self) -> None:
        """有持仓 + 除息日 → 分红再投"""
        div = {pd.Timestamp("2024-01-05"): 0.1}
        result = reinvest_dividends(1000, 2.0, pd.Timestamp("2024-01-05"), div)
        assert result == pytest.approx(1000 * 0.1 / 2.0)

    def test_no_position(self) -> None:
        """units=0 → 分红不处理"""
        div = {pd.Timestamp("2024-01-05"): 0.1}
        result = reinvest_dividends(0, 2.0, pd.Timestamp("2024-01-05"), div)
        assert result == 0.0

    def test_not_ex_date(self) -> None:
        """非除息日 → 不处理"""
        div = {pd.Timestamp("2024-01-05"): 0.1}
        result = reinvest_dividends(1000, 2.0, pd.Timestamp("2024-01-06"), div)
        assert result == 0.0

    def test_empty_dict(self) -> None:
        """空分红字典 → 不处理"""
        result = reinvest_dividends(1000, 2.0, pd.Timestamp("2024-01-05"), {})
        assert result == 0.0


# =============================================================================
# calc_redeem_fee 测试
# =============================================================================


class TestCalcRedeemFee:
    def test_single_batch_short_term(self) -> None:
        """单批次 < 7 天 → 1.5%"""
        batches = [{"date": pd.Timestamp("2024-01-01"), "units": 1000}]
        fee = calc_redeem_fee(batches, pd.Timestamp("2024-01-03"), 1.5)
        assert fee == pytest.approx(1000 * 1.5 * 0.015)

    def test_multi_batch_different_rates(self) -> None:
        """多批次各落入不同费率区间"""
        batches = [
            {"date": pd.Timestamp("2024-01-01"), "units": 1000},  # 持有 1 天 → 1.5%
            {"date": pd.Timestamp("2023-12-01"), "units": 500},  # 持有 32 天 → 0.5%
        ]
        fee = calc_redeem_fee(batches, pd.Timestamp("2024-01-02"), 2.0)
        # batch1: 1000 * 2.0 * 0.015 = 30
        # batch2: 500 * 2.0 * 0.005 = 5 (32天 → 30<32≤365 费率0.5%)
        # total = 35.0
        assert fee == pytest.approx(35.0)

    def test_no_fee_after_730_days(self) -> None:
        """持有 > 730 天 → 0%"""
        batches = [{"date": pd.Timestamp("2022-01-01"), "units": 1000}]
        fee = calc_redeem_fee(batches, pd.Timestamp("2024-01-05"), 2.0)
        assert fee == 0.0

    def test_empty_batches(self) -> None:
        """空批次列表 → 0"""
        fee = calc_redeem_fee([], pd.Timestamp("2024-01-05"), 2.0)
        assert fee == 0.0

    def test_custom_schedule(self) -> None:
        """自定义费率阶梯"""
        schedule = [(30, 0.01), (90, 0.005), (float("inf"), 0.0)]
        batches = [{"date": pd.Timestamp("2024-01-01"), "units": 1000}]
        fee = calc_redeem_fee(batches, pd.Timestamp("2024-01-15"), 1.0, schedule)
        assert fee == pytest.approx(1000 * 1.0 * 0.01)

    def test_zero_hold_days(self) -> None:
        """同日购入（持有 0 天）→ 0%（0 < 0 不成立）"""
        batches = [{"date": pd.Timestamp("2024-01-05"), "units": 1000}]
        fee = calc_redeem_fee(batches, pd.Timestamp("2024-01-05"), 1.5)
        assert fee == 0.0

    def test_boundary_7_days(self) -> None:
        """持有 7 天 → 1.5%（0 < 7 ≤ 7）"""
        batches = [{"date": pd.Timestamp("2024-01-01"), "units": 1000}]
        fee = calc_redeem_fee(batches, pd.Timestamp("2024-01-08"), 1.0)
        assert fee == pytest.approx(1000 * 1.0 * 0.015)

    def test_boundary_30_days(self) -> None:
        """持有 30 天 → 0.75%（7 < 30 ≤ 30）"""
        batches = [{"date": pd.Timestamp("2024-01-01"), "units": 1000}]
        fee = calc_redeem_fee(batches, pd.Timestamp("2024-01-31"), 1.0)
        assert fee == pytest.approx(1000 * 1.0 * 0.0075)

    def test_boundary_365_days(self) -> None:
        """持有 365 天 → 0.50%（30 < 365 ≤ 365）"""
        batches = [{"date": pd.Timestamp("2024-01-01"), "units": 1000}]
        fee = calc_redeem_fee(batches, pd.Timestamp("2024-12-31"), 1.0)
        assert fee == pytest.approx(1000 * 1.0 * 0.005)

    def test_boundary_730_days(self) -> None:
        """持有 730 天 → 0.25%（365 < 730 ≤ 730）"""
        batches = [{"date": pd.Timestamp("2022-01-01"), "units": 1000}]
        fee = calc_redeem_fee(batches, pd.Timestamp("2023-12-31"), 1.0)
        assert fee == pytest.approx(1000 * 1.0 * 0.0025)


# =============================================================================
# build_dividend_dict 测试
# =============================================================================


class TestBuildDividendDict:
    def test_basic(self) -> None:
        df = pd.DataFrame({"除息日": [pd.Timestamp("2024-01-05"), pd.Timestamp("2024-06-01")], "每份分红": [0.1, 0.05]})
        result = build_dividend_dict(df)
        assert result == {pd.Timestamp("2024-01-05"): 0.1, pd.Timestamp("2024-06-01"): 0.05}

    def test_empty_dataframe(self) -> None:
        result = build_dividend_dict(pd.DataFrame())
        assert result == {}

    def test_none_input(self) -> None:
        result = build_dividend_dict(None)
        assert result == {}


# =============================================================================
# fetch_dividend_data 测试（mock DB + AKShare）
# =============================================================================


class TestFetchDividendData:
    """fetch_dividend_data 缓存/API 路径测试"""

    @patch("backend.dca_backtest.db.fund_dividend.save")
    @patch("backend.dca_backtest.db.fund_dividend.load")
    @patch("backend.dca_backtest.db.init_db")
    def test_cache_hit(self, mock_init: MagicMock, mock_load: MagicMock, mock_save: MagicMock) -> None:
        """缓存命中 → 直接返回缓存数据，日期转为 Timestamp"""
        mock_load.return_value = pd.DataFrame(
            {
                "除息日": ["2024-01-05", "2024-06-01"],
                "每份分红": [0.1, 0.05],
            }
        )
        result = fetch_dividend_data("000000")
        assert len(result) == 2
        assert pd.api.types.is_datetime64_any_dtype(result["除息日"])
        assert result["每份分红"].tolist() == [0.1, 0.05]
        mock_save.assert_not_called()

    @patch("backend.dca_backtest.db.fund_dividend.save")
    @patch("backend.dca_backtest.db.fund_dividend.load")
    @patch("backend.dca_backtest.ak.fund_open_fund_info_em")
    @patch("backend.dca_backtest.db.init_db")
    def test_cache_miss_api_success(
        self, mock_init: MagicMock, mock_api: MagicMock, mock_load: MagicMock, mock_save: MagicMock
    ) -> None:
        """缓存未命中，API 返回数据 → 处理后返回并写入缓存"""
        mock_load.return_value = None
        mock_api.return_value = pd.DataFrame(
            {
                "除息日": pd.to_datetime(["2024-06-15", "2024-12-20"]),
                "每份分红": ["0.0800 元", "0.0500 元"],
                "分红方案": ["每份派现金0.0800元", "每份派现金0.0500元"],
            }
        )
        result = fetch_dividend_data("000000")
        assert len(result) == 2
        assert pd.api.types.is_datetime64_any_dtype(result["除息日"])
        assert result["每份分红"].tolist() == [0.08, 0.05]
        mock_save.assert_called_once()
        saved = mock_save.call_args[0][1]
        assert list(saved.columns) == ["除息日", "每份分红"]

    @patch("backend.dca_backtest.db.fund_dividend.load")
    @patch("backend.dca_backtest.ak.fund_open_fund_info_em")
    @patch("backend.dca_backtest.db.init_db")
    def test_cache_miss_api_empty(self, mock_init: MagicMock, mock_api: MagicMock, mock_load: MagicMock) -> None:
        """缓存未命中，API 返回空 DataFrame → 返回空"""
        mock_load.return_value = None
        mock_api.return_value = pd.DataFrame()
        result = fetch_dividend_data("000000")
        assert result.empty

    @patch("backend.dca_backtest.db.fund_dividend.load")
    @patch("backend.dca_backtest.ak.fund_open_fund_info_em")
    @patch("backend.dca_backtest.db.init_db")
    def test_cache_miss_api_no_data_text(self, mock_init: MagicMock, mock_api: MagicMock, mock_load: MagicMock) -> None:
        """缓存未命中，API 返回含"暂无"的 DataFrame → 返回空"""
        mock_load.return_value = None
        mock_api.return_value = pd.DataFrame({"info": ["暂无数据"]})
        result = fetch_dividend_data("000000")
        assert result.empty

    @patch("backend.dca_backtest.db.fund_dividend.load")
    @patch("backend.dca_backtest.ak.fund_open_fund_info_em")
    @patch("backend.dca_backtest.db.init_db")
    def test_cache_miss_api_exception(self, mock_init: MagicMock, mock_api: MagicMock, mock_load: MagicMock) -> None:
        """缓存未命中，API 抛出异常 → 返回空"""
        mock_load.return_value = None
        mock_api.side_effect = Exception("API timeout")
        result = fetch_dividend_data("000000")
        assert result.empty
