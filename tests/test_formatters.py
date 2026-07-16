"""backend/formatters.py 格式化函数测试"""

import pandas as pd

from backend.formatters import fmt_nav, fmt_pct, fmt_scale, fmt_total_fee


class TestFmtPct:
    def test_normal_float(self) -> None:
        assert fmt_pct(12.345) == "12.35%"

    def test_string_with_pct(self) -> None:
        assert fmt_pct("8.5%") == "8.50%"

    def test_string_without_pct(self) -> None:
        assert fmt_pct("6.0") == "6.00%"

    def test_zero(self) -> None:
        assert fmt_pct(0) == "0.00%"

    def test_nan(self) -> None:
        assert fmt_pct(float("nan")) == "—"

    def test_none(self) -> None:
        assert fmt_pct(None) == "—"

    def test_empty_string(self) -> None:
        assert fmt_pct("") == "—"

    def test_pd_na(self) -> None:
        assert fmt_pct(pd.NA) == "—"

    def test_non_numeric_string(self) -> None:
        assert fmt_pct("N/A") == "N/A"


class TestFmtNav:
    def test_normal_float(self) -> None:
        assert fmt_nav(1.2345) == "1.2345"

    def test_three_decimals(self) -> None:
        assert fmt_nav(2.0) == "2.0000"

    def test_string_number(self) -> None:
        assert fmt_nav("3.1415") == "3.1415"

    def test_nan(self) -> None:
        assert fmt_nav(float("nan")) == "—"

    def test_none(self) -> None:
        assert fmt_nav(None) == "—"

    def test_empty_string(self) -> None:
        assert fmt_nav("") == "—"

    def test_pd_na(self) -> None:
        assert fmt_nav(pd.NA) == "—"

    def test_non_numeric_string(self) -> None:
        assert fmt_nav("unknown") == "unknown"


class TestFmtScale:
    def test_over_one_yi(self) -> None:
        assert fmt_scale(5.678) == "5.7亿"

    def test_exactly_one_yi(self) -> None:
        assert fmt_scale(1.0) == "1.0亿"

    def test_under_one_yi_to_wan(self) -> None:
        assert fmt_scale(0.1234) == "1234万"

    def test_small_value(self) -> None:
        assert fmt_scale(0.0005) == "5万"

    def test_zero(self) -> None:
        assert fmt_scale(0) == "0万"

    def test_nan(self) -> None:
        assert fmt_scale(float("nan")) == "—"

    def test_none(self) -> None:
        assert fmt_scale(None) == "—"

    def test_empty_string(self) -> None:
        assert fmt_scale("") == "—"

    def test_pd_na(self) -> None:
        assert fmt_scale(pd.NA) == "—"

    def test_non_numeric_string(self) -> None:
        assert fmt_scale("not_a_number") == "not_a_number"


class TestFmtTotalFee:
    def test_only_total(self) -> None:
        row = {"综合费率": 1.50}
        result = fmt_total_fee(row)
        assert result == "1.50%"

    def test_total_with_all_details(self) -> None:
        row = {
            "申购费": 0.15,
            "管理费": 1.20,
            "托管费": 0.20,
            "销售服务费": 0.0,
            "综合费率": 1.55,
        }
        result = fmt_total_fee(row)
        assert "1.55%" in result
        assert "申0.15%" in result
        assert "管1.20%" in result
        assert "托0.20%" in result
        assert "销0.00%" in result

    def test_no_total_with_details(self) -> None:
        row = {"申购费": 0.15, "管理费": 1.20, "托管费": 0.20, "销售服务费": 0.0}
        result = fmt_total_fee(row)
        assert "—" in result
        assert "申0.15%" in result
        assert "管1.20%" in result

    def test_total_with_buy_mgmt_cust(self) -> None:
        row = {"申购费": 0.12, "管理费": 1.50, "托管费": 0.25, "综合费率": 1.87}
        result = fmt_total_fee(row)
        assert "1.87%" in result
        assert "申0.12%" in result
        assert "管1.50%" in result
        assert "托0.25%" in result

    def test_only_buy_fee(self) -> None:
        row = {"申购费": 0.10}
        result = fmt_total_fee(row)
        assert "—" in result
        assert "申0.10%" in result

    def test_empty_row(self) -> None:
        assert fmt_total_fee({}) == "—"

    def test_all_nan(self) -> None:
        row = {"申购费": float("nan"), "管理费": float("nan"), "综合费率": float("nan")}
        result = fmt_total_fee(row)
        assert result == "—"
