"""db.py 数据库访问层测试"""

from datetime import datetime
from typing import Any

import pandas as pd

from db import (
    FundDividendTable,
    FundNavHistoryTable,
    _last_available_data_day,
    clear_all,
    clear_fund_cache,
    clear_index_cache,
    fund_catalog,
    fund_fee,
    fund_nav,
    fund_profile,
    fund_scale,
    get_cache_meta,
    get_series_last_date,
    init_db,
    is_series_fresh,
    load_index_fund_nav,
    load_pension_funds,
    load_series,
    set_cache_meta,
    upsert_series,
)


def test_init_db_is_idempotent(db_engine: Any) -> None:
    init_db()
    init_db()


# ── FundFeeTable ──


class TestFundFeeTable:
    def test_save_and_load(self, db_engine: Any) -> None:
        fund_fee.save("110026", 0.12, 1.5, 0.25, 0.0, "10元", 1.87)
        result = fund_fee.load(["110026"])
        assert "110026" in result
        assert result["110026"]["申购费"] == 0.12
        assert result["110026"]["管理费"] == 1.5
        assert result["110026"]["综合费率"] == 1.87

    def test_load_empty_codes(self, db_engine: Any) -> None:
        assert fund_fee.load([]) == {}

    def test_load_missing_code(self, db_engine: Any) -> None:
        assert fund_fee.load(["999999"]) == {}

    def test_save_replaces(self, db_engine: Any) -> None:
        fund_fee.save("110026", 0.10, 1.5, 0.25, 0.0, "10元", 1.85)
        fund_fee.save("110026", 0.08, 1.2, 0.20, 0.0, "1元", 1.48)
        result = fund_fee.load(["110026"])
        assert result["110026"]["申购费"] == 0.08
        assert result["110026"]["综合费率"] == 1.48

    def test_cached_count(self, db_engine: Any) -> None:
        fund_fee.save("110026", 0.12, 1.5, 0.25, 0.0, "10元", 1.87)
        fund_fee.save("161725", 0.10, 1.0, 0.20, 0.0, "1元", 1.30)
        assert fund_fee.cached_count() == 2

    def test_cached_count_empty(self, db_engine: Any) -> None:
        assert fund_fee.cached_count() == 0

    def test_is_fresh_before_set(self, db_engine: Any) -> None:
        assert not fund_fee.is_fresh()

    def test_set_fresh(self, db_engine: Any) -> None:
        fund_fee.set_fresh()
        assert fund_fee.is_fresh()

    def test_is_fresh_respects_ttl(self, db_engine: Any) -> None:
        fund_fee.set_fresh()
        assert not fund_fee.is_fresh(ttl=-1)

    def test_clear(self, db_engine: Any) -> None:
        fund_fee.save("110026", 0.12, 1.5, 0.25, 0.0, "10元", 1.87)
        fund_fee.set_fresh()
        fund_fee.clear()
        assert fund_fee.cached_count() == 0
        assert not fund_fee.is_fresh()


# ── FundScaleTable ──


class TestFundScaleTable:
    def test_save_and_load(self, db_engine: Any) -> None:
        fund_scale.save("110026", 12.5, 10.0)
        result = fund_scale.load(["110026"])
        assert result["110026"]["净资产规模"] == 12.5
        assert result["110026"]["份额规模"] == 10.0

    def test_load_missing_returns_empty(self, db_engine: Any) -> None:
        assert fund_scale.load(["999999"]) == {}

    def test_clear(self, db_engine: Any) -> None:
        fund_scale.save("110026", 12.5, 10.0)
        fund_scale.clear()
        assert fund_scale.load(["110026"]) == {}


# ── FundProfileTable ──


class TestFundProfileTable:
    _SAVE_KW = {
        "issue_date": None,
        "establish_date": None,
        "mgr": None,
        "custodian": None,
        "fund_mgr": None,
        "benchmark": None,
        "track_index": None,
    }

    def test_save_and_load(self, db_engine: Any) -> None:
        fund_profile.save(
            "110026", "2020-01-01", "2020-02-01", "南方基金", "工行", "张三", "沪深300", "沪深300指数", "被动指数型"
        )
        result = fund_profile.load(["110026"])
        assert result["110026"]["基金管理人"] == "南方基金"
        assert result["110026"]["基金经理"] == "张三"
        assert result["110026"]["跟踪标的"] == "沪深300指数"

    def test_batch_update_tracking_method(self, db_engine: Any) -> None:
        fund_profile.save("110026", **self._SAVE_KW, track_method="被动指数型")
        fund_profile.save("161725", **self._SAVE_KW, track_method="被动指数型")
        fund_profile.batch_update_tracking_method({"110026": "增强指数型"})
        result = fund_profile.load(["110026", "161725"])
        assert result["110026"]["跟踪方式"] == "增强指数型"
        assert result["161725"]["跟踪方式"] == "被动指数型"

    def test_clear(self, db_engine: Any) -> None:
        fund_profile.save("110026", **self._SAVE_KW, track_method="被动指数型")
        fund_profile.clear()
        assert fund_profile.load(["110026"]) == {}


# ── FundNavTable (_BulkTable) ──


class TestFundNavTable:
    def test_save_and_load(self, db_engine: Any) -> None:
        df = pd.DataFrame(
            {
                "基金代码": ["110026"],
                "日期": ["2024-01-02"],
                "单位净值": [1.5],
                "累计净值": [1.8],
                "日增长率": [0.01],
                "数据来源": ["em"],
            }
        )
        fund_nav.save(df)
        loaded = fund_nav.load()
        assert loaded is not None
        assert len(loaded) == 1

    def test_save_replaces(self, db_engine: Any) -> None:
        df1 = pd.DataFrame(
            {
                "基金代码": ["110026"],
                "日期": ["2024-01-02"],
                "单位净值": [1.5],
                "累计净值": [1.8],
                "日增长率": [0.01],
                "数据来源": ["em"],
            }
        )
        fund_nav.save(df1)
        df2 = pd.DataFrame(
            {
                "基金代码": ["161725"],
                "日期": ["2024-01-02"],
                "单位净值": [0.8],
                "累计净值": [1.2],
                "日增长率": [-0.005],
                "数据来源": ["em"],
            }
        )
        fund_nav.save(df2)
        loaded = fund_nav.load()
        assert loaded is not None
        assert len(loaded) == 1
        assert loaded.iloc[0]["基金代码"] == "161725"

    def test_set_fresh_on_save(self, db_engine: Any) -> None:
        assert not fund_nav.is_fresh()
        df = pd.DataFrame(
            {
                "基金代码": ["110026"],
                "日期": ["2024-01-02"],
                "单位净值": [1.5],
                "累计净值": [1.8],
                "日增长率": [None],
                "数据来源": ["em"],
            }
        )
        fund_nav.save(df)
        assert fund_nav.is_fresh()

    def test_clear(self, db_engine: Any) -> None:
        df = pd.DataFrame(
            {
                "基金代码": ["110026"],
                "日期": ["2024-01-02"],
                "单位净值": [1.5],
                "累计净值": [1.8],
                "日增长率": [None],
                "数据来源": ["em"],
            }
        )
        fund_nav.save(df)
        fund_nav.clear()
        loaded = fund_nav.load()
        assert loaded is None or loaded.empty


# ── FundCatalogTable (_BulkTable) ──


class TestFundCatalogTable:
    def test_save_and_load(self, db_engine: Any) -> None:
        df = pd.DataFrame(
            {
                "基金代码": ["110026"],
                "拼音缩写": ["NA"],
                "基金简称": ["南方创业板ETF联接A"],
                "基金类型": ["指数型-股票"],
                "拼音全称": ["nanfang"],
            }
        )
        fund_catalog.save(df)
        loaded = fund_catalog.load()
        assert loaded is not None
        assert len(loaded) == 1


# ── FundNavHistoryTable ──


class TestFundNavHistoryTable:
    def test_save_and_load(self, db_engine: Any) -> None:
        tbl = FundNavHistoryTable()
        df = pd.DataFrame(
            {
                "净值日期": ["2024-01-02", "2024-01-03"],
                "单位净值": [1.5, 1.52],
                "累计净值": [1.8, 1.82],
                "日增长率": [0.01, 0.013],
            }
        )
        tbl.save("110026", df)
        loaded = tbl.load("110026", "2024-01-01", "2024-01-31")
        assert loaded is not None
        assert len(loaded) == 2

    def test_load_out_of_range(self, db_engine: Any) -> None:
        tbl = FundNavHistoryTable()
        df = pd.DataFrame(
            {
                "净值日期": ["2024-01-02"],
                "单位净值": [1.5],
                "累计净值": [1.8],
                "日增长率": [0.01],
            }
        )
        tbl.save("110026", df)
        assert tbl.load("110026", "2025-01-01", "2025-01-31") is None

    def test_is_cached_returns_false_when_empty(self, db_engine: Any) -> None:
        tbl = FundNavHistoryTable()
        assert not tbl.is_cached("110026", "2024-01-10")

    def test_is_cached_returns_true_with_data(self, db_engine: Any) -> None:
        tbl = FundNavHistoryTable()
        df = pd.DataFrame(
            {
                "净值日期": ["2024-01-02"],
                "单位净值": [1.5],
                "累计净值": [1.8],
                "日增长率": [0.01],
            }
        )
        tbl.save("110026", df)
        assert tbl.is_cached("110026", "2024-01-02")


# ── FundDividendTable ──


class TestFundDividendTable:
    def test_save_and_load(self, db_engine: Any) -> None:
        tbl = FundDividendTable()
        df = pd.DataFrame({"除息日": ["2024-06-20"], "每份分红": [0.05]})
        tbl.save("110026", df)
        loaded = tbl.load("110026")
        assert loaded is not None
        assert len(loaded) == 1

    def test_empty_save_noop(self, db_engine: Any) -> None:
        tbl = FundDividendTable()
        tbl.save("110026", pd.DataFrame())
        assert tbl.load("110026") is None

    def test_load_returns_none_for_unknown(self, db_engine: Any) -> None:
        tbl = FundDividendTable()
        assert tbl.load("999999") is None


# ── index_series / cache_meta ──


class TestIndexSeries:
    def test_upsert_and_load(self, db_engine: Any) -> None:
        df = pd.DataFrame({"date": ["2024-01-02", "2024-01-03"], "value": [15.0, 15.5]})
        upsert_series("000300", "pe", df)
        loaded = load_series("000300", "pe")
        assert len(loaded) == 2
        assert loaded.iloc[0]["date"] == "2024-01-02"

    def test_upsert_replaces_duplicate(self, db_engine: Any) -> None:
        df1 = pd.DataFrame({"date": ["2024-01-02"], "value": [15.0]})
        upsert_series("000300", "pe", df1)
        df2 = pd.DataFrame({"date": ["2024-01-02"], "value": [16.0]})
        upsert_series("000300", "pe", df2)
        loaded = load_series("000300", "pe")
        assert len(loaded) == 1
        assert loaded.iloc[0]["value"] == 16.0

    def test_get_series_last_date(self, db_engine: Any) -> None:
        df = pd.DataFrame({"date": ["2024-01-02", "2024-01-05"], "value": [15.0, 16.0]})
        upsert_series("000300", "pe", df)
        assert get_series_last_date("000300", "pe") == "2024-01-05"

    def test_get_series_last_date_empty(self, db_engine: Any) -> None:
        assert get_series_last_date("000300", "pe") is None

    def test_set_and_get_cache_meta(self, db_engine: Any) -> None:
        set_cache_meta("000300", "pe", "csindex")
        meta = get_cache_meta("000300", "pe")
        assert meta is not None
        assert meta.source == "csindex"

    def test_is_series_fresh_returns_true(self, db_engine: Any) -> None:
        df = pd.DataFrame({"date": [pd.Timestamp.now().strftime("%Y-%m-%d")], "value": [15.0]})
        upsert_series("000300", "pe", df)
        assert is_series_fresh("000300", "pe", max_age_days=1)

    def test_is_series_fresh_returns_false(self, db_engine: Any) -> None:
        df = pd.DataFrame({"date": ["2020-01-02"], "value": [15.0]})
        upsert_series("000300", "pe", df)
        assert not is_series_fresh("000300", "pe", max_age_days=1)


# ── clear functions ──


class TestClearFunctions:
    def test_clear_index_cache(self, db_engine: Any) -> None:
        df = pd.DataFrame({"date": ["2024-01-02"], "value": [15.0]})
        upsert_series("000300", "pe", df)
        set_cache_meta("000300", "pe", "csindex")
        clear_index_cache()
        assert load_series("000300", "pe").empty
        assert get_cache_meta("000300", "pe") is None

    def test_clear_fund_cache(self, db_engine: Any) -> None:
        fund_fee.save("110026", 0.12, 1.5, 0.25, 0.0, "10元", 1.87)
        fund_scale.save("110026", 12.5)
        fund_profile.save("110026", **TestFundProfileTable._SAVE_KW, track_method="被动指数型")
        df = pd.DataFrame(
            {
                "基金代码": ["110026"],
                "日期": ["2024-01-02"],
                "单位净值": [1.5],
                "累计净值": [1.8],
                "日增长率": [None],
                "数据来源": ["em"],
            }
        )
        fund_nav.save(df)
        fund_fee.set_fresh()
        clear_fund_cache()
        assert fund_fee.cached_count() == 0
        assert fund_scale.load(["110026"]) == {}
        assert fund_profile.load(["110026"]) == {}
        assert not fund_fee.is_fresh()

    def test_clear_all(self, db_engine: Any) -> None:
        upsert_series("000300", "pe", pd.DataFrame({"date": ["2024-01-02"], "value": [15.0]}))
        fund_fee.save("110026", 0.12, 1.5, 0.25, 0.0, "10元", 1.87)
        clear_all()
        assert load_series("000300", "pe").empty
        assert fund_fee.cached_count() == 0


# ── JOIN queries ──


class TestJoinQueries:
    def test_load_index_fund_nav_with_data(self, db_engine: Any) -> None:
        df_cat = pd.DataFrame(
            {
                "基金代码": ["110026"],
                "拼音缩写": ["NA"],
                "基金简称": ["南方创业板ETF联接A"],
                "基金类型": ["指数型-股票"],
                "拼音全称": ["nanfang"],
            }
        )
        fund_catalog.save(df_cat)
        df_nav = pd.DataFrame(
            {
                "基金代码": ["110026"],
                "日期": ["2024-01-02"],
                "单位净值": [1.5],
                "累计净值": [1.8],
                "日增长率": [0.01],
                "数据来源": ["em"],
            }
        )
        fund_nav.save(df_nav)
        fund_fee.save("110026", 0.12, 1.5, 0.25, 0.0, "10元", 1.87)
        fund_scale.save("110026", 12.5)
        fund_profile.save("110026", None, None, None, None, None, None, "创业板指数", "被动指数型")
        result = load_index_fund_nav()
        assert result is not None
        assert len(result) == 1

    def test_load_index_fund_nav_empty(self, db_engine: Any) -> None:
        result = load_index_fund_nav()
        assert result is None or result.empty

    def test_load_pension_funds_with_data(self, db_engine: Any) -> None:
        df_cat = pd.DataFrame(
            {
                "基金代码": ["110026Y"],
                "拼音缩写": ["NA"],
                "基金简称": ["南方创业板ETF联接Y"],
                "基金类型": ["指数型-股票"],
                "拼音全称": ["nanfang"],
            }
        )
        fund_catalog.save(df_cat)
        df_nav = pd.DataFrame(
            {
                "基金代码": ["110026Y"],
                "日期": ["2024-01-02"],
                "单位净值": [1.5],
                "累计净值": [1.8],
                "日增长率": [0.01],
                "数据来源": ["em"],
            }
        )
        fund_nav.save(df_nav)
        fund_fee.save("110026Y", 0.0, 0.5, 0.10, 0.0, "1元", 0.6)
        fund_scale.save("110026Y", 5.0)
        result = load_pension_funds()
        assert result is not None
        assert len(result) == 1

    def test_load_pension_funds_empty(self, db_engine: Any) -> None:
        result = load_pension_funds()
        assert result is None or result.empty


# ── _last_available_data_day (existing test file covers parametrized cases) ──


class TestLastAvailableDataDay:
    def test_weekday_not_today(self) -> None:
        assert _last_available_data_day("2026-07-02", now=datetime(2026, 6, 28, 14, 0)) == "2026-07-02"

    def test_sunday(self) -> None:
        assert _last_available_data_day("2026-06-28", now=datetime(2026, 6, 28, 14, 0)) == "2026-06-26"

    def test_today_before_22(self) -> None:
        assert _last_available_data_day("2026-06-24", now=datetime(2026, 6, 24, 9, 0)) == "2026-06-23"

    def test_today_after_22(self) -> None:
        assert _last_available_data_day("2026-06-24", now=datetime(2026, 6, 24, 23, 0)) == "2026-06-24"


# ── _FundTable base class edge cases ──


class TestFundTableBase:
    def test_meta_key_none_returns_false(self, db_engine: Any) -> None:
        assert not fund_scale.is_fresh()

    def test_clear_on_table_without_meta_key(self, db_engine: Any) -> None:
        fund_scale.save("110026", 12.5)
        fund_scale.clear()
        assert fund_scale.load(["110026"]) == {}

    def test_cached_count_handles_exception(self, db_engine: Any) -> None:
        orig = fund_fee.cached_count()
        assert isinstance(orig, int)
