"""分类逻辑测试 — 纯函数，零外部依赖"""

from backend.index_fund import (
    classify_fund_type,
    classify_share_class,
    _normalize_index_name,
    _tokenize,
)
from backend.pension_fund import classify_pension_category


class TestClassifyFundType:
    def test_etf_join(self):
        assert classify_fund_type("华夏沪深300ETF联接A") == "ETF联接"

    def test_etf(self):
        assert classify_fund_type("沪深300ETF") == "ETF"
        assert classify_fund_type("养殖ETF华安") == "ETF"

    def test_enhanced(self):
        assert classify_fund_type("富国沪深300增强A") == "指数增强"
        assert classify_fund_type("易方达沪深300量化增强") == "指数增强"

    def test_regular(self):
        assert classify_fund_type("华夏沪深300A") == "普通指数型"


class TestClassifyShareClass:
    def test_a_share(self):
        assert classify_share_class("招商中证白酒A") == "A类"

    def test_c_share(self):
        assert classify_share_class("招商中证白酒C") == "C类"

    def test_y_share(self):
        assert classify_share_class("易方达沪深300ETF联接Y") == "Y类"

    def test_e_share(self):
        assert classify_share_class("某基金E") == "E类"

    def test_other(self):
        assert classify_share_class("某基金") == "其他"


class TestNormalizeIndexName:
    def test_strip_suffix(self):
        assert _normalize_index_name("沪深300指数") == "沪深300"

    def test_strip_price(self):
        assert _normalize_index_name("中证白酒价格指数") == "中证白酒"

    def test_none(self):
        assert _normalize_index_name(None) is None

    def test_no_suffix(self):
        assert _normalize_index_name("中证红利") == "中证红利"


class TestTokenize:
    def test_chinese_bigrams(self):
        assert _tokenize("沪深300") == ["沪深", "300"]

    def test_mixed(self):
        assert _tokenize("中证白酒A") == ["中证", "白酒", "A"]

    def test_short_chinese(self):
        assert _tokenize("白酒") == ["白酒"]


class TestClassifyPensionCategory:
    def test_index(self):
        row = {"基金名称": "某沪深300Y", "基金类型": "指数型-股票"}
        assert classify_pension_category(row) == "指数基金"

    def test_fof_target_date(self):
        row = {"基金名称": "养老目标日期2035Y", "基金类型": "FOF"}
        assert classify_pension_category(row) == "FOF-目标日期"

    def test_fof_risk_robust(self):
        row = {"基金名称": "某稳健养老Y", "基金类型": "FOF-稳健型"}
        assert classify_pension_category(row) == "FOF-目标风险-稳健"

    def test_fof_risk_balanced(self):
        row = {"基金名称": "某均衡养老Y", "基金类型": "FOF-均衡型"}
        assert classify_pension_category(row) == "FOF-目标风险-均衡"

    def test_other(self):
        row = {"基金名称": "某货币Y", "基金类型": "货币型"}
        assert classify_pension_category(row) == "其他"
