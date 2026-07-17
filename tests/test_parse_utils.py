"""parse_utils 纯函数单元测试 — 无外部依赖，零 mock"""

import pandas as pd
import pytest

from backend.parse_utils import normalize, normalize_nav_df, parse_pct, parse_pct_series, parse_scale, to_float_series


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


class TestNormalize:
    def test_remove_index_suffix(self) -> None:
        assert normalize("沪深300指数") == "沪深300"

    def test_remove_price_suffix(self) -> None:
        assert normalize("中证500(价格)") == "中证500"

    def test_remove_industry_suffix(self) -> None:
        assert normalize("信息技术(行业)") == "信息技术"

    def test_remove_space(self) -> None:
        assert normalize("中证 500") == "中证500"

    def test_remove_currency_suffix(self) -> None:
        assert normalize("恒生指数港元") == "恒生"

    def test_remove_currency_rmb(self) -> None:
        assert normalize("上证50人民币") == "上证50"

    def test_break_on_first_currency_match(self) -> None:
        assert normalize("美元人民币") == "美元"

    def test_remove_halfwidth_brackets(self) -> None:
        assert normalize("中证消费(HS)") == "中证消费"

    def test_remove_fullwidth_brackets(self) -> None:
        assert normalize("中证消费（全收益）") == "中证消费"

    def test_fullwidth_open_halfwidth_close(self) -> None:
        assert normalize("中证消费（全收益)") == "中证消费"

    def test_strip_whitespace(self) -> None:
        assert normalize("  沪深300  ") == "沪深300"

    def test_no_change(self) -> None:
        assert normalize("沪深300") == "沪深300"

    def test_multiple_suffixes(self) -> None:
        assert normalize("中证500(价格)人民币") == "中证500"

    def test_empty_string(self) -> None:
        assert normalize("") == ""


class TestNormalizeNavDf:
    def test_basic_normalization(self) -> None:
        df = pd.DataFrame(
            {
                "净值日期": ["2024-01-02", "2024-01-03"],
                "单位净值": ["1.5", "1.6"],
                "累计净值": ["2.0", "2.1"],
                "日增长率": ["0.5", "-0.3"],
            }
        )
        result = normalize_nav_df(df)
        assert result["date"].tolist() == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]
        assert result["unit_nav"].tolist() == [1.5, 1.6]
        assert result["acc_nav"].tolist() == [2.0, 2.1]
        assert result["daily_return"].tolist() == [0.5, -0.3]

    def test_coerce_non_numeric(self) -> None:
        df = pd.DataFrame(
            {
                "净值日期": ["2024-01-02"],
                "单位净值": ["---"],
                "累计净值": [None],
                "日增长率": ["0.5"],
            }
        )
        result = normalize_nav_df(df)
        assert pd.isna(result["unit_nav"].iloc[0])
        assert pd.isna(result["acc_nav"].iloc[0])
        assert result["daily_return"].iloc[0] == 0.5

    def test_original_columns_preserved(self) -> None:
        df = pd.DataFrame(
            {
                "净值日期": ["2024-01-02"],
                "单位净值": ["1.5"],
                "累计净值": ["2.0"],
                "日增长率": ["0.5%"],
            }
        )
        result = normalize_nav_df(df)
        assert "净值日期" in result.columns
        assert "单位净值" in result.columns
