"""parse_utils 纯函数单元测试 — 无外部依赖，零 mock"""

import pandas as pd
import pytest

from backend.parse_utils import parse_pct, parse_pct_series, parse_scale, to_float_series


class TestParsePct:
    def test_pct(self) -> None:
        assert parse_pct("1.5%") == 1.5

    def test_pct_with_nian(self) -> None:
        assert parse_pct("0.15%（每年）") == 0.15

    def test_dash(self) -> None:
        assert parse_pct("---") is None

    def test_whitespace(self) -> None:
        assert parse_pct("  0.5  ") == 0.5

    def test_none_input(self) -> None:
        assert parse_pct(None) is None

    def test_empty_string(self) -> None:
        assert parse_pct("") is None

    def test_invalid(self) -> None:
        assert parse_pct("abc") is None

    def test_zero(self) -> None:
        assert parse_pct("0") == 0.0

    def test_integer_string(self) -> None:
        assert parse_pct("3") == 3.0


class TestParseScale:
    def test_yi(self) -> None:
        assert parse_scale("1.23亿") == 1.23

    def test_yi_fractional(self) -> None:
        assert parse_scale("0.5亿") == 0.5

    def test_wan(self) -> None:
        assert parse_scale("5000万") == pytest.approx(0.5)

    def test_wan_small(self) -> None:
        assert parse_scale("10万") == pytest.approx(0.001)

    def test_bare_number_as_yi(self) -> None:
        """裸数字（无亿/万后缀）→ 视为已是亿原样返回"""
        assert parse_scale("59.14") == 59.14

    def test_none_input(self) -> None:
        assert parse_scale(None) is None

    def test_empty_string(self) -> None:
        assert parse_scale("") is None

    def test_dash(self) -> None:
        assert parse_scale("---") is None

    def test_no_number_text(self) -> None:
        assert parse_scale("暂无") is None

    def test_integer_string(self) -> None:
        assert parse_scale("1") == 1.0


class TestParsePctSeries:
    def test_basic(self) -> None:
        s = pd.Series(["1.5%", "0.2%", "---"])
        result = parse_pct_series(s)
        assert result.iloc[0] == 1.5
        assert result.iloc[1] == 0.2
        assert pd.isna(result.iloc[2])

    def test_nan_values(self) -> None:
        s = pd.Series(["", "nan", None])
        result = parse_pct_series(s)
        assert result.isna().all()

    def test_whitespace_in_pct(self) -> None:
        s = pd.Series(["5%", "10 %"])
        result = parse_pct_series(s)
        assert result.tolist() == [5.0, 10.0]

    def test_mixed_valid_invalid(self) -> None:
        s = pd.Series(["3.5%", "abc", "1.0%", "---"])
        result = parse_pct_series(s)
        assert result.iloc[0] == 3.5
        assert pd.isna(result.iloc[1])
        assert result.iloc[2] == 1.0
        assert pd.isna(result.iloc[3])

    def test_all_valid(self) -> None:
        s = pd.Series(["1%", "2.5%", "0.05%"])
        result = parse_pct_series(s)
        assert result.tolist() == [1.0, 2.5, 0.05]


class TestToFloatSeries:
    def test_basic(self) -> None:
        s = pd.Series(["1.5", "2.3", "nan"])
        result = to_float_series(s)
        assert result.iloc[0] == 1.5
        assert result.iloc[1] == 2.3
        assert pd.isna(result.iloc[2])

    def test_placeholder_values(self) -> None:
        s = pd.Series(["", "None", "3.0"])
        result = to_float_series(s)
        assert pd.isna(result.iloc[0])
        assert pd.isna(result.iloc[1])
        assert result.iloc[2] == 3.0

    def test_all_nan(self) -> None:
        s = pd.Series(["", "nan", "<NA>"])
        result = to_float_series(s)
        assert result.isna().all()

    def test_all_valid(self) -> None:
        s = pd.Series(["10", "20.5", "30"])
        result = to_float_series(s)
        assert result.tolist() == [10.0, 20.5, 30.0]
