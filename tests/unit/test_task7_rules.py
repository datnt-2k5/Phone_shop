
"""Unit Test Task 7: SQL Mode, Clock và Decimal."""

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from database.connection import ensure_strict_mode
from utils.money_utils import (
    quantize_money,
    weighted_average_cost,
)
from utils.time_utils import FixedClock, utc_to_vn


class FakeCursor:
    """Giả lập Cursor của database để kiểm thử."""

    def __init__(self, sql_mode: str) -> None:
        self.sql_mode = sql_mode
        self.statements = []
        self.closed = False

    def execute(self, statement, params=None):
        self.statements.append((statement, params))

    def fetchone(self):
        return (self.sql_mode,)

    def close(self):
        self.closed = True


class FakeConnection:
    """Giả lập Connection, không cần MariaDB."""

    def __init__(self, sql_mode: str) -> None:
        self.fake_cursor = FakeCursor(sql_mode)

    def cursor(self):
        return self.fake_cursor


def test_db07_existing_modes_preserved():
    """Strict Mode đã bật thì không thay đổi SQL Mode."""

    dbapi = FakeConnection(
        "ANSI_QUOTES,STRICT_ALL_TABLES,NO_ZERO_DATE"
    )

    ensure_strict_mode(dbapi, None)

    assert len(dbapi.fake_cursor.statements) == 1
    assert dbapi.fake_cursor.closed


def test_db08_missing_strict_is_added_without_removing_modes():
    """Chỉ bổ sung Strict Mode, giữ các mode cũ."""

    dbapi = FakeConnection(
        "ANSI_QUOTES,NO_ZERO_DATE"
    )

    ensure_strict_mode(dbapi, None)

    statements = dbapi.fake_cursor.statements

    assert len(statements) == 2

    sql, params = statements[1]

    assert sql == "SET SESSION sql_mode = %s"
    assert params is not None

    modes = set(params[0].split(","))

    assert modes == {
        "ANSI_QUOTES",
        "NO_ZERO_DATE",
        "STRICT_TRANS_TABLES",
    }

    assert dbapi.fake_cursor.closed


def test_clock_independent_with_different_timezones():
    """Hai FixedClock phải độc lập với nhau."""

    first = FixedClock(
        datetime(2026, 11, 4, 10, 0, tzinfo=UTC)
    )

    second = FixedClock(
        datetime(
            2026,
            11,
            5,
            10,
            0,
            tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"),
        )
    )

    first.set_time(
        datetime(2026, 11, 4, 11, 0, tzinfo=UTC)
    )

    assert first.now_utc() == datetime(
        2026, 11, 4, 11, 0
    )

    assert second.now_utc() == datetime(
        2026, 11, 5, 3, 0
    )

    # 17:30 UTC ngày 04/11 = 00:30 VN ngày 05/11
    vn_date = utc_to_vn(
        datetime(2026, 11, 4, 17, 30)
    ).date()

    assert vn_date.isoformat() == "2026-11-05"


def test_money_round_half_up_positive_and_negative():
    """Kiểm tra quy tắc làm tròn HALF_UP."""

    assert quantize_money("2.005") == Decimal("2.01")
    assert quantize_money("-2.005") == Decimal("-2.01")
    assert quantize_money("2.004") == Decimal("2.00")


def test_weighted_average_import_and_restore():
    """Kiểm tra giá vốn bình quân gia quyền."""

    assert weighted_average_cost(
        10, "5000000", 5, "5500000"
    ) == Decimal("5166666.67")

    assert weighted_average_cost(
        5, "6000000", 1, "5000000"
    ) == Decimal("5833333.33")
