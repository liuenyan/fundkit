"""买入/卖出策略单元测试"""

import math

import pandas as pd

from backend.strategy import (
    BuyAction,
    DCAPosition,
    FixedBuyStrategy,
    MovingAverageBuyStrategy,
    TargetProfitSellStrategy,
    TrailingStopSellStrategy,
    ValueAveragingBuyStrategy,
)


class TestFixedBuyStrategy:
    def test_buy_on_invest_date(self) -> None:
        s = FixedBuyStrategy(1000, 0.0015)
        action = s.should_buy(pd.Timestamp("2024-01-01"), 1.0, DCAPosition(), {pd.Timestamp("2024-01-01")})
        assert action == BuyAction(amount=1000, fee_rate=0.0015)

    def test_skip_when_not_invest_set(self) -> None:
        s = FixedBuyStrategy(1000, 0.0015)
        action = s.should_buy(pd.Timestamp("2024-01-01"), 1.0, DCAPosition(), set())
        assert action == BuyAction(0)

    def test_skip_when_inactive(self) -> None:
        s = FixedBuyStrategy(1000, 0.0015)
        pos = DCAPosition(is_active=False)
        action = s.should_buy(pd.Timestamp("2024-01-01"), 1.0, pos, {pd.Timestamp("2024-01-01")})
        assert action == BuyAction(0)

    def test_deviation_and_multiplier_are_none(self) -> None:
        s = FixedBuyStrategy(500, 0.001)
        action = s.should_buy(pd.Timestamp("2024-01-01"), 1.0, DCAPosition(), {pd.Timestamp("2024-01-01")})
        assert action.deviation is None
        assert action.multiplier is None


class TestValueAveragingBuyStrategy:
    def test_buy_amount(self) -> None:
        s = ValueAveragingBuyStrategy(1000, 4.0, 10, 0.0015)
        pos = DCAPosition()
        action = s.should_buy(pd.Timestamp("2024-01-01"), 1.0, pos, {pd.Timestamp("2024-01-01")})
        assert action.amount >= 10

    def test_reset_clears_period_count(self) -> None:
        s = ValueAveragingBuyStrategy(1000, 4.0, 10, 0.0015)
        pos = DCAPosition()
        s.should_buy(pd.Timestamp("2024-01-01"), 1.0, pos, {pd.Timestamp("2024-01-01")})
        assert s.period_count == 1
        s.on_reset()
        assert s.period_count == 0

    def test_min_amount_when_target_exceeded(self) -> None:
        s = ValueAveragingBuyStrategy(1000, 4.0, 50, 0.0015)
        pos = DCAPosition(units=500)
        action = s.should_buy(pd.Timestamp("2024-01-01"), 10.0, pos, {pd.Timestamp("2024-01-01")})
        assert action.amount == 50

    def test_max_amount_cap(self) -> None:
        s = ValueAveragingBuyStrategy(1000, 4.0, 10, 0.0015)
        pos = DCAPosition(units=0)
        # after 4 periods: target = 4000, current = 0, required = 4000
        s.period_count = 4
        action = s.should_buy(pd.Timestamp("2024-01-01"), 10.0, pos, {pd.Timestamp("2024-01-01")})
        assert action.amount == 4000

    def test_normal_amount(self) -> None:
        s = ValueAveragingBuyStrategy(1000, 4.0, 10, 0.0015)
        pos = DCAPosition(units=30)
        action = s.should_buy(pd.Timestamp("2024-01-02"), 10.0, pos, {pd.Timestamp("2024-01-02")})
        assert action.amount > 10

    def test_skip_when_inactive(self) -> None:
        s = ValueAveragingBuyStrategy(1000, 4.0, 10, 0.0015)
        pos = DCAPosition(is_active=False)
        action = s.should_buy(pd.Timestamp("2024-01-01"), 1.0, pos, {pd.Timestamp("2024-01-01")})
        assert action.amount == 0

    def test_skip_when_not_in_invest_set(self) -> None:
        s = ValueAveragingBuyStrategy(1000, 4.0, 10, 0.0015)
        action = s.should_buy(pd.Timestamp("2024-01-01"), 1.0, DCAPosition(), set())
        assert action.amount == 0

    def test_period_count_increments(self) -> None:
        s = ValueAveragingBuyStrategy(1000, 4.0, 10, 0.0015)
        s.should_buy(pd.Timestamp("2024-01-01"), 1.0, DCAPosition(), {pd.Timestamp("2024-01-01")})
        s.should_buy(pd.Timestamp("2024-02-01"), 1.0, DCAPosition(), {pd.Timestamp("2024-02-01")})
        assert s.period_count == 2

    def test_rounds_up_amount(self) -> None:
        s = ValueAveragingBuyStrategy(1000, 4.0, 10, 0.0015)
        pos = DCAPosition(units=0.33)
        action = s.should_buy(pd.Timestamp("2024-01-01"), 10.0, pos, {pd.Timestamp("2024-01-01")})
        assert action.amount == math.ceil(action.amount * 100) / 100


class TestMovingAverageBuyStrategy:
    def _make_nav_df(self, vals: list[float]) -> pd.DataFrame:
        dates = pd.date_range("2024-01-01", periods=len(vals), freq="D")
        return pd.DataFrame({"date": dates, "unit_nav": vals})

    def _ma_test_case(self, target_deviation: float) -> tuple[MovingAverageBuyStrategy, pd.Timestamp, float]:
        """构造均线策略测试场景，返回 (strategy, date, nav) 使得偏离度 = target_deviation"""
        nav_vals = [1.0] * 500  # 前 500 天恒为 1.0，均线 = 1.0
        nav_vals.append(1.0 + target_deviation)  # 第 501 天按偏离度设置净值
        df = self._make_nav_df(nav_vals)
        nav = df["unit_nav"].iloc[-1]
        s = MovingAverageBuyStrategy(1000, 250, 0.0015, df)
        return s, df["date"].iloc[-1], nav

    def test_buy_on_undervalue_multiple_2x(self) -> None:
        s, date, nav = self._ma_test_case(-0.15)  # 偏离 -15%
        action = s.should_buy(date, nav, DCAPosition(), {date})
        assert action.amount == 2000  # < -10% → 2.0x
        assert action.fee_rate == 0.0015

    def test_buy_on_overvalue_stop(self) -> None:
        s, date, nav = self._ma_test_case(0.10)  # 偏离 +10%
        action = s.should_buy(date, nav, DCAPosition(), {date})
        assert action.amount == 0  # >= 5% → 0x 停投

    def test_buy_on_slight_undervalue_1x(self) -> None:
        s, date, nav = self._ma_test_case(-0.02)  # 偏离 -2%
        action = s.should_buy(date, nav, DCAPosition(), {date})
        assert action.amount == 1000  # -5% ~ 0 → 1.0x

    def test_buy_on_slight_overvalue_05x(self) -> None:
        s, date, nav = self._ma_test_case(0.02)  # 偏离 +2%
        action = s.should_buy(date, nav, DCAPosition(), {date})
        assert action.amount == 500  # 0 ~ 5% → 0.5x

    def test_buy_on_moderate_undervalue_15x(self) -> None:
        s, date, nav = self._ma_test_case(-0.08)  # 偏离 -8%
        action = s.should_buy(date, nav, DCAPosition(), {date})
        assert action.amount == 1500  # -10% ~ -5% → 1.5x

    def test_fallback_when_no_ma_available(self) -> None:
        df = self._make_nav_df([1.0] * 10)
        s = MovingAverageBuyStrategy(1000, 250, 0.0015, df)
        action = s.should_buy(df["date"].iloc[-1], df["unit_nav"].iloc[-1], DCAPosition(), {df["date"].iloc[-1]})
        assert action.amount == 1000  # fallback to base_amount

    def test_skip_when_not_in_invest_set(self) -> None:
        df = self._make_nav_df([1.0] * 300)
        s = MovingAverageBuyStrategy(1000, 250, 0.0015, df)
        action = s.should_buy(df["date"].iloc[-1], df["unit_nav"].iloc[-1], DCAPosition(), set())
        assert action.amount == 0

    def test_skip_when_inactive(self) -> None:
        df = self._make_nav_df([1.0] * 300)
        s = MovingAverageBuyStrategy(1000, 250, 0.0015, df)
        pos = DCAPosition(is_active=False)
        action = s.should_buy(df["date"].iloc[-1], df["unit_nav"].iloc[-1], pos, {df["date"].iloc[-1]})
        assert action.amount == 0

    def test_aggressive_mode_tiers(self) -> None:
        tiers, mults = MovingAverageBuyStrategy.MA_MODES["aggressive"]
        assert tiers == (-0.15, -0.08, -0.03, 0.03)
        assert mults == (3.0, 2.0, 1.5, 0.5, 0.0)

    def test_conservative_mode_tiers(self) -> None:
        tiers, mults = MovingAverageBuyStrategy.MA_MODES["conservative"]
        assert tiers == (-0.08, -0.04, 0, 0.04)
        assert mults == (1.5, 1.2, 1.0, 0.8, 0.0)

    def test_custom_tiers_and_multipliers(self) -> None:
        nav_vals = [1.0] * 300 + [0.75]  # deviation ≈ -0.25 -> < -0.2 -> 5.0x
        df = self._make_nav_df(nav_vals)
        tiers = (-0.2, -0.1)
        mults = (5.0, 2.0, 0.0)
        s = MovingAverageBuyStrategy(1000, 250, 0.0015, df, tiers, mults)
        date = df["date"].iloc[-1]
        nav = df["unit_nav"].iloc[-1]
        action = s.should_buy(date, nav, DCAPosition(), {date})
        assert action.amount == 5000
        assert action.multiplier == 5.0

    def test_uses_acc_nav_when_available(self) -> None:
        dates = pd.date_range("2024-01-01", periods=300, freq="D")
        df = pd.DataFrame({"date": dates, "acc_nav": [1.0] * 300, "unit_nav": [0.9] * 300})
        s = MovingAverageBuyStrategy(1000, 250, 0.0015, df)
        date = df["date"].iloc[-1]
        action = s.should_buy(date, 1.0, DCAPosition(), {date})
        assert action.deviation is not None

    def test_returns_deviation_and_multiplier(self) -> None:
        df = self._make_nav_df([1.0] * 300)
        s = MovingAverageBuyStrategy(1000, 250, 0.0015, df)
        date = df["date"].iloc[-1]
        action = s.should_buy(date, df["unit_nav"].iloc[-1], DCAPosition(), {date})
        assert action.deviation is not None
        assert action.multiplier is not None


class TestTrailingStopSellStrategy:
    def test_no_sell_when_no_position(self) -> None:
        s = TrailingStopSellStrategy(0.20, 0.08)
        signal = s.evaluate(pd.Timestamp("2024-01-01"), 1.0, DCAPosition(), 0, 0)
        assert not signal.should_sell

    def test_stop_buy_when_return_above_threshold(self) -> None:
        s = TrailingStopSellStrategy(0.20, 0.08)
        pos = DCAPosition(units=100, cost=1000)
        signal = s.evaluate(pd.Timestamp("2024-01-01"), 15.0, pos, 1500, 0.25)
        assert signal.stop_buying

    def test_sell_on_trailing_stop(self) -> None:
        s = TrailingStopSellStrategy(0.20, 0.08)
        pos = DCAPosition(units=100, is_active=False, peak_return=0.30)
        signal = s.evaluate(pd.Timestamp("2024-01-01"), 12.0, pos, 1200, 0.15)
        assert signal.should_sell

    def test_no_sell_when_still_active(self) -> None:
        s = TrailingStopSellStrategy(0.20, 0.08)
        pos = DCAPosition(units=100, is_active=True, peak_return=0.30)
        signal = s.evaluate(pd.Timestamp("2024-01-01"), 12.0, pos, 1200, 0.20)
        assert not signal.should_sell

    def test_no_sell_on_insufficient_drawdown(self) -> None:
        s = TrailingStopSellStrategy(0.20, 0.08)
        pos = DCAPosition(units=100, is_active=False, peak_return=0.25)
        signal = s.evaluate(pd.Timestamp("2024-01-01"), 13.0, pos, 1300, 0.22)
        assert not signal.should_sell

    def test_no_sell_when_no_units(self) -> None:
        s = TrailingStopSellStrategy(0.20, 0.08)
        pos = DCAPosition(units=0, is_active=False, peak_return=0.30)
        signal = s.evaluate(pd.Timestamp("2024-01-01"), 12.0, pos, 0, 0.20)
        assert not signal.should_sell
        assert not signal.stop_buying


class TestTargetProfitSellStrategy:
    def test_sell_on_target(self) -> None:
        s = TargetProfitSellStrategy(0.20)
        pos = DCAPosition(units=100)
        signal = s.evaluate(pd.Timestamp("2024-01-01"), 15.0, pos, 1500, 0.25)
        assert signal.should_sell

    def test_no_sell_below_target(self) -> None:
        s = TargetProfitSellStrategy(0.20)
        pos = DCAPosition(units=100)
        signal = s.evaluate(pd.Timestamp("2024-01-01"), 10.0, pos, 1000, 0.10)
        assert not signal.should_sell

    def test_no_sell_when_no_units(self) -> None:
        s = TargetProfitSellStrategy(0.20)
        pos = DCAPosition(units=0)
        signal = s.evaluate(pd.Timestamp("2024-01-01"), 15.0, pos, 0, 0.25)
        assert not signal.should_sell


class TestDCAPosition:
    def test_default_values(self) -> None:
        pos = DCAPosition()
        assert pos.units == 0.0
        assert pos.is_active is True

    def test_custom_values(self) -> None:
        pos = DCAPosition(units=100, cost=5000, is_active=False)
        assert pos.units == 100
        assert pos.cost == 5000
        assert pos.is_active is False


class TestBuyAction:
    def test_default_values(self) -> None:
        action = BuyAction()
        assert action.amount == 0.0
        assert action.deviation is None
        assert action.multiplier is None

    def test_custom_values(self) -> None:
        action = BuyAction(amount=1000, fee_rate=0.0015, deviation=-0.05, multiplier=1.5)
        assert action.amount == 1000
        assert action.deviation == -0.05
        assert action.multiplier == 1.5
