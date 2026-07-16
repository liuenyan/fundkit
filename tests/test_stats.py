"""backend/stats.py 纯函数测试"""

import math

import pandas as pd
import pytest

from backend.stats import (
    annualized_volatility,
    calc_annualized,
    calc_percentile,
    calmar_ratio,
    max_drawdown,
    max_drawdown_duration,
    profit_loss_ratio,
    sharpe_ratio,
    win_rate,
)


class TestMaxDrawdown:
    def test_monotonic_rising(self) -> None:
        s = pd.Series([100.0, 110.0, 120.0, 130.0])
        assert max_drawdown(s) == 0.0

    def test_single_drawdown(self) -> None:
        s = pd.Series([100.0, 110.0, 80.0, 90.0])
        result = max_drawdown(s)
        expected = (80 - 110) / 110
        assert result == pytest.approx(expected)

    def test_multiple_drawdowns_takes_max(self) -> None:
        s = pd.Series([100.0, 120.0, 90.0, 110.0, 70.0])
        result = max_drawdown(s)
        expected = (70 - 120) / 120
        assert result == pytest.approx(expected)

    def test_no_recovery(self) -> None:
        s = pd.Series([100.0, 90.0, 80.0])
        result = max_drawdown(s)
        expected = (80 - 100) / 100
        assert result == pytest.approx(expected)

    def test_single_element(self) -> None:
        assert max_drawdown(pd.Series([100.0])) == 0.0

    def test_empty_series(self) -> None:
        assert math.isnan(max_drawdown(pd.Series([], dtype=float)))


class TestCalcAnnualized:
    def test_double_in_one_year(self) -> None:
        ret = calc_annualized(1.0, pd.Timestamp("2023-01-01"), pd.Timestamp("2024-01-01"))
        assert ret == pytest.approx(1.0)

    def test_half_year_26pct(self) -> None:
        ret = calc_annualized(0.26, pd.Timestamp("2023-01-01"), pd.Timestamp("2023-07-02"))
        days = 182
        expected = (1 + 0.26) ** (365 / days) - 1
        assert ret == pytest.approx(expected)

    def test_zero_days(self) -> None:
        ret = calc_annualized(0.5, pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-01"))
        assert ret == 0.0

    def test_negative_days(self) -> None:
        ret = calc_annualized(0.5, pd.Timestamp("2024-01-10"), pd.Timestamp("2024-01-01"))
        assert ret == 0.0

    def test_zero_return(self) -> None:
        ret = calc_annualized(0.0, pd.Timestamp("2024-01-01"), pd.Timestamp("2025-01-01"))
        assert ret == 0.0

    def test_negative_return(self) -> None:
        ret = calc_annualized(-0.5, pd.Timestamp("2023-01-01"), pd.Timestamp("2024-01-01"))
        assert ret == pytest.approx(-0.5)


class TestCalcPercentile:
    def test_last_is_highest(self) -> None:
        s = pd.Series([1.0, 2.0, 3.0])
        assert calc_percentile(s) == pytest.approx(66.6667, rel=1e-3)

    def test_last_is_lowest(self) -> None:
        s = pd.Series([3.0, 2.0, 1.0])
        assert calc_percentile(s) == 0.0

    def test_last_is_middle(self) -> None:
        s = pd.Series([1.0, 3.0, 2.0])
        assert calc_percentile(s) == pytest.approx(33.3333, rel=1e-3)

    def test_fewer_than_two_values(self) -> None:
        assert calc_percentile(pd.Series([1.0])) is None
        assert calc_percentile(pd.Series([], dtype=float)) is None

    def test_with_nan(self) -> None:
        s = pd.Series([1.0, float("nan"), 3.0, 2.0])
        assert calc_percentile(s) == pytest.approx(33.3333, rel=1e-3)


class TestAnnualizedVolatility:
    def test_constant_series(self) -> None:
        s = pd.Series([100.0, 100.0, 100.0, 100.0])
        assert annualized_volatility(s) == 0.0

    def test_less_than_two_returns(self) -> None:
        s = pd.Series([100.0, 101.0])
        assert annualized_volatility(s) == 0.0

    def test_increasing_series(self) -> None:
        s = pd.Series([100.0, 102.0, 101.0, 105.0])
        vol = annualized_volatility(s)
        assert vol > 0

    def test_with_total_invested(self) -> None:
        total_value = pd.Series([100.0, 200.0, 300.0, 400.0])
        total_invested = pd.Series([100.0, 200.0, 300.0, 400.0])
        vol = annualized_volatility(total_value, total_invested)
        assert vol == 0.0

    def test_with_dates(self) -> None:
        dates = pd.Series(pd.date_range("2024-01-01", periods=5, freq="ME"))
        s = pd.Series([100.0, 105.0, 103.0, 108.0, 106.0])
        vol = annualized_volatility(s, dates=dates)
        assert vol > 0


class TestSharpeRatio:
    def test_zero_vol(self) -> None:
        assert sharpe_ratio(0.1, 0.0) == 0.0

    def test_positive(self) -> None:
        assert sharpe_ratio(0.10, 0.15) == pytest.approx(0.6667, rel=1e-3)

    def test_with_risk_free(self) -> None:
        assert sharpe_ratio(0.10, 0.15, risk_free=0.02) == pytest.approx(0.5333, rel=1e-3)

    def test_negative_return(self) -> None:
        assert sharpe_ratio(-0.05, 0.15) == pytest.approx(-0.3333, rel=1e-3)


class TestCalmarRatio:
    def test_zero_mdd(self) -> None:
        assert calmar_ratio(0.15, 0.0) == 0.0

    def test_positive(self) -> None:
        assert calmar_ratio(0.15, -0.20) == pytest.approx(0.75)

    def test_negative_return(self) -> None:
        assert calmar_ratio(-0.10, -0.30) == pytest.approx(-0.3333, rel=1e-3)


class TestWinRate:
    def test_all_positive(self) -> None:
        s = pd.Series([0.01, 0.02, 0.03])
        assert win_rate(s) == 1.0

    def test_all_negative(self) -> None:
        s = pd.Series([-0.01, -0.02, -0.03])
        assert win_rate(s) == 0.0

    def test_mixed(self) -> None:
        s = pd.Series([0.01, -0.01, 0.02, -0.02, 0.03])
        assert win_rate(s) == 0.6

    def test_with_nan(self) -> None:
        s = pd.Series([0.01, float("nan"), -0.01, 0.02])
        assert win_rate(s) == 2 / 3

    def test_empty(self) -> None:
        assert win_rate(pd.Series([], dtype=float)) == 0.0

    def test_zero_values(self) -> None:
        s = pd.Series([0.0, 0.0, 0.0])
        assert win_rate(s) == 0.0


class TestProfitLossRatio:
    def test_all_gains(self) -> None:
        s = pd.Series([0.01, 0.02, 0.03])
        assert profit_loss_ratio(s) == 0.0

    def test_all_losses(self) -> None:
        s = pd.Series([-0.01, -0.02, -0.03])
        assert profit_loss_ratio(s) == 0.0

    def test_mixed(self) -> None:
        s = pd.Series([0.05, -0.02, 0.06, -0.01, 0.04])
        avg_gain = (0.05 + 0.06 + 0.04) / 3
        avg_loss = (-0.02 + -0.01) / 2
        assert profit_loss_ratio(s) == pytest.approx(avg_gain / abs(avg_loss))

    def test_empty(self) -> None:
        assert profit_loss_ratio(pd.Series([], dtype=float)) == 0.0

    def test_single_gain(self) -> None:
        s = pd.Series([0.05])
        assert profit_loss_ratio(s) == 0.0

    def test_single_loss(self) -> None:
        s = pd.Series([-0.05])
        assert profit_loss_ratio(s) == 0.0


class TestMaxDrawdownDuration:
    def test_monotonic_rising(self) -> None:
        s = pd.Series([100.0, 110.0, 120.0])
        assert max_drawdown_duration(s) == 0

    def test_single_drawdown(self) -> None:
        s = pd.Series([100.0, 110.0, 90.0, 80.0, 120.0])
        assert max_drawdown_duration(s) == 2

    def test_multiple_drawdowns_longest(self) -> None:
        s = pd.Series([100.0, 80.0, 70.0, 120.0, 110.0, 100.0, 90.0])
        assert max_drawdown_duration(s) == 3

    def test_no_recovery(self) -> None:
        s = pd.Series([100.0, 90.0, 80.0, 70.0])
        assert max_drawdown_duration(s) == 3

    def test_with_dates_returns_calendar_days(self) -> None:
        dates = pd.Series(pd.date_range("2024-01-01", periods=5, freq="D"))
        s = pd.Series([100.0, 110.0, 90.0, 80.0, 120.0])
        assert max_drawdown_duration(s, dates) == 2

    def test_with_dates_gap(self) -> None:
        dates = pd.Series(pd.date_range("2024-01-01", periods=5, freq="4D"))
        s = pd.Series([100.0, 110.0, 90.0, 80.0, 120.0])
        assert max_drawdown_duration(s, dates) == 8

    def test_single_element(self) -> None:
        assert max_drawdown_duration(pd.Series([100.0])) == 0
