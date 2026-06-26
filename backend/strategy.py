"""定投策略模块

买入策略 + 卖出策略的接口与内置实现。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class DCAPosition:
    """定投模拟状态"""
    units: float = 0.0
    cost: float = 0.0        # 当前轮次累计投入金额
    total_invested: float = 0.0
    total_recovered: float = 0.0
    is_active: bool = True
    peak_return: float = -float("inf")
    fee_batches: list[dict] = field(default_factory=list)


@dataclass
class BuyAction:
    """买入动作"""
    amount: float = 0.0  # 0 = 不投


class BuyStrategy(ABC):
    """买入策略基类"""

    @abstractmethod
    def should_buy(self, date: pd.Timestamp, nav: float, pos: DCAPosition,
                   invest_set: set[pd.Timestamp]) -> BuyAction: ...


class FixedBuyStrategy(BuyStrategy):
    """定期定额买入"""

    def __init__(self, amount: float, purchase_rate: float) -> None:
        self.amount = amount
        self.purchase_rate = purchase_rate

    def should_buy(self, date: pd.Timestamp, nav: float, pos: DCAPosition,
                   invest_set: set[pd.Timestamp]) -> BuyAction:
        if pos.is_active and date in invest_set:
            return BuyAction(amount=self.amount)
        return BuyAction(0)


@dataclass
class SellSignal:
    """卖出信号"""
    should_sell: bool = False
    reason: str = ""
    stop_buying: bool = False  # 策略B: 通知主循环停止定投


class SellStrategy(ABC):
    """卖出策略基类"""

    @abstractmethod
    def evaluate(self, date: pd.Timestamp, nav: float, pos: DCAPosition,
                 mkt_value: float, round_return: float) -> SellSignal: ...

    def on_reset(self) -> None:
        """卖出后重置策略内部状态（默认无操作）"""
        return


class TargetProfitSellStrategy(SellStrategy):
    """目标止盈（策略A）"""

    def __init__(self, take_profit: float) -> None:
        self.take_profit = take_profit

    def evaluate(self, date: pd.Timestamp, nav: float, pos: DCAPosition,
                 mkt_value: float, round_return: float) -> SellSignal:
        if pos.units > 0 and round_return >= self.take_profit:
            return SellSignal(should_sell=True, reason=f"目标收益率 {self.take_profit * 100:.0f}%")
        return SellSignal()


class TrailingStopSellStrategy(SellStrategy):
    """停投持有+移动止盈（策略B）"""

    def __init__(self, stop_invest: float, trailing_stop: float) -> None:
        self.stop_invest = stop_invest
        self.trailing_stop = trailing_stop

    def evaluate(self, date: pd.Timestamp, nav: float, pos: DCAPosition,
                 mkt_value: float, round_return: float) -> SellSignal:
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
