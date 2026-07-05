"""定投策略模块

买入策略 + 卖出策略的接口与内置实现。
"""

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pandas as pd

INF = float("inf")


@dataclass
class DCAPosition:
    """定投模拟状态"""

    units: float = 0.0
    cost: float = 0.0  # 当前轮次累计投入金额
    total_invested: float = 0.0
    total_recovered: float = 0.0
    is_active: bool = True
    peak_return: float = -INF
    fee_batches: list[dict] = field(default_factory=list)


@dataclass
class BuyAction:
    """买入动作"""

    amount: float = 0.0  # 总投入金额（含申购费），0 = 不投
    fee_rate: float = 0.0  # 申购费率（如 0.0015）


class BuyStrategy(ABC):
    """买入策略基类"""

    @abstractmethod
    def should_buy(
        self, date: pd.Timestamp, nav: float, pos: DCAPosition, invest_set: set[pd.Timestamp]
    ) -> BuyAction: ...

    def on_reset(self) -> None:
        """卖出后重置策略内部状态（默认无操作）"""
        return


class MovingAverageBuyStrategy(BuyStrategy):
    """指数均线策略：偏离均线越远买入越多"""

    DEFAULT_TIERS = (-0.10, -0.05, 0, 0.05)
    DEFAULT_MULTIPLIERS = (2.0, 1.5, 1.0, 0.5, 0.0)

    MA_MODES: dict[str, tuple[tuple[float, ...], tuple[float, ...]]] = {
        "default": (DEFAULT_TIERS, DEFAULT_MULTIPLIERS),
        "aggressive": ((-0.15, -0.08, -0.03, 0.03), (3.0, 2.0, 1.5, 0.5, 0.0)),
        "conservative": ((-0.08, -0.04, 0, 0.04), (1.5, 1.2, 1.0, 0.8, 0.0)),
    }

    def __init__(
        self,
        base_amount: float,
        period: int,
        purchase_rate: float,
        nav_df: pd.DataFrame,
        tiers: tuple[float, ...] | None = None,
        multipliers: tuple[float, ...] | None = None,
    ) -> None:
        self.base_amount = base_amount
        self.period = period
        self.purchase_rate = purchase_rate
        self.tiers = tiers or self.DEFAULT_TIERS
        self.multipliers = multipliers or self.DEFAULT_MULTIPLIERS
        # 优先用累计净值（平滑，无分红跳降），回退单位净值
        col = "acc_nav" if "acc_nav" in nav_df.columns else "unit_nav"
        self._nav_index = nav_df.set_index("date")[col]
        self.ma_series = self._nav_index.rolling(window=period, min_periods=period).mean()

    def should_buy(self, date: pd.Timestamp, nav: float, pos: DCAPosition, invest_set: set[pd.Timestamp]) -> BuyAction:
        if not pos.is_active or date not in invest_set:
            return BuyAction(0)

        ma = self.ma_series.get(date, None)
        if ma is None or pd.isna(ma) or ma == 0:
            return BuyAction(amount=self.base_amount, fee_rate=self.purchase_rate)

        current = self._nav_index.get(date, nav)
        deviation = (current - ma) / ma
        multiple = self._deviation_to_multiple(deviation)
        amount = self.base_amount * multiple
        return BuyAction(amount=max(amount, 0) if amount > 0 else 0, fee_rate=self.purchase_rate)

    def _deviation_to_multiple(self, deviation: float) -> float:
        for i, threshold in enumerate(self.tiers):
            if deviation < threshold:
                return self.multipliers[i]
        return self.multipliers[-1]


class FixedBuyStrategy(BuyStrategy):
    """定期定额买入"""

    def __init__(self, amount: float, purchase_rate: float) -> None:
        self.amount = amount
        self.purchase_rate = purchase_rate

    def should_buy(self, date: pd.Timestamp, nav: float, pos: DCAPosition, invest_set: set[pd.Timestamp]) -> BuyAction:
        if pos.is_active and date in invest_set:
            return BuyAction(amount=self.amount, fee_rate=self.purchase_rate)
        return BuyAction(0)


class ValueAveragingBuyStrategy(BuyStrategy):
    """价值平均：以每期增长固定市值为目标"""

    def __init__(
        self,
        target_value_increment: float,
        max_multiple: float = 4.0,
        min_amount: float = 10.0,
        purchase_rate: float = 0.0015,
    ) -> None:
        self.target = target_value_increment
        self.max_amount = target_value_increment * max_multiple
        self.min_amount = min_amount
        self.purchase_rate = purchase_rate
        self.period_count = 0

    def should_buy(self, date: pd.Timestamp, nav: float, pos: DCAPosition, invest_set: set[pd.Timestamp]) -> BuyAction:
        if not pos.is_active or date not in invest_set:
            return BuyAction(0)

        self.period_count += 1
        target_value = self.period_count * self.target
        current_value = pos.units * nav
        required = target_value - current_value

        if required <= 0:
            return BuyAction(amount=self.min_amount, fee_rate=self.purchase_rate)

        amount = min(required, self.max_amount)
        amount = math.ceil(amount * 100) / 100
        return BuyAction(amount=amount, fee_rate=self.purchase_rate)

    def on_reset(self) -> None:
        self.period_count = 0


@dataclass
class SellSignal:
    """卖出信号"""

    should_sell: bool = False
    reason: str = ""
    stop_buying: bool = False  # 策略B: 通知主循环停止定投


class SellStrategy(ABC):
    """卖出策略基类"""

    @abstractmethod
    def evaluate(
        self, date: pd.Timestamp, nav: float, pos: DCAPosition, mkt_value: float, round_return: float
    ) -> SellSignal: ...

    def on_reset(self) -> None:
        """卖出后重置策略内部状态（默认无操作）"""
        return


class TargetProfitSellStrategy(SellStrategy):
    """目标止盈（策略A）"""

    def __init__(self, take_profit: float) -> None:
        self.take_profit = take_profit

    def evaluate(
        self, date: pd.Timestamp, nav: float, pos: DCAPosition, mkt_value: float, round_return: float
    ) -> SellSignal:
        if pos.units > 0 and round_return >= self.take_profit:
            return SellSignal(should_sell=True, reason=f"目标收益率 {self.take_profit * 100:.0f}%")
        return SellSignal()


class TrailingStopSellStrategy(SellStrategy):
    """停投持有+移动止盈（策略B）"""

    def __init__(self, stop_invest: float, trailing_stop: float) -> None:
        self.stop_invest = stop_invest
        self.trailing_stop = trailing_stop

    def evaluate(
        self, date: pd.Timestamp, nav: float, pos: DCAPosition, mkt_value: float, round_return: float
    ) -> SellSignal:
        if pos.units > 0 and round_return >= self.stop_invest:
            return SellSignal(stop_buying=True)

        if (
            not pos.is_active
            and pos.units > 0
            and pos.peak_return >= self.trailing_stop
            and round_return <= pos.peak_return - self.trailing_stop
        ):
            return SellSignal(should_sell=True, reason=f"移动止盈（回撤 {self.trailing_stop * 100:.0f}%）")

        return SellSignal()
