"""_last_available_data_day + FundNavHistoryTable.is_cached 测试"""

from datetime import datetime

import pytest

from db import _last_available_data_day


class TestLastAvailableDataDay:
    @pytest.mark.parametrize(
        ("end_date", "now", "expected"),
        [
            # 1 周日 → 本周五
            ("2026-06-28", datetime(2026, 6, 28, 14, 0), "2026-06-26"),
            # 2 周四（非今天）→ 自身
            ("2026-07-02", datetime(2026, 6, 28, 14, 0), "2026-07-02"),
            # 3 周六 → 本周五
            ("2026-06-27", datetime(2026, 6, 27, 14, 0), "2026-06-26"),
            # 4 周三（今天, 09:00 < 22）→ 上一个交易日（周二）
            ("2026-06-24", datetime(2026, 6, 24, 9, 0), "2026-06-23"),
            # 5 周三（今天, 23:00 ≥ 22）→ 自身
            ("2026-06-24", datetime(2026, 6, 24, 23, 0), "2026-06-24"),
            # 6 周一（今天, 09:00 < 22）→ 上一个交易日（上周五，跳过周末）
            ("2026-06-29", datetime(2026, 6, 29, 9, 0), "2026-06-26"),
            # 7 上周日（非今天）→ 上周五
            ("2026-06-21", datetime(2026, 6, 24, 9, 0), "2026-06-19"),
            # 8 周五非今天 → 自身
            ("2026-06-26", datetime(2026, 6, 28, 14, 0), "2026-06-26"),
            # 9 今天周五 08:00 → 上一个交易日（周四）
            ("2026-06-26", datetime(2026, 6, 26, 8, 0), "2026-06-25"),
        ],
    )
    def test_given_scenarios(self, end_date: str, now: datetime, expected: str) -> None:
        assert _last_available_data_day(end_date, now=now) == expected
