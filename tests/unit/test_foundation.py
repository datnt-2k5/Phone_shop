"""Kiểm thử hạ tầng Task 5; chạy: python -m pytest tests/unit/test_foundation.py -v"""
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from models.app_error import AppError
from services.base_service import BaseService
from utils.code_utils import generate_code, generate_temp_code
from utils.money_utils import quantize_money, weighted_average_cost
from utils.time_utils import FixedClock, SystemClock, utc_to_vn


def test_app_error():
    error = AppError("OUT_OF_STOCK", "Không đủ hàng", {"stock": "0"})
    assert str(error) == "Không đủ hàng"
    assert error.to_dict() == {
        "error_code": "OUT_OF_STOCK",
        "message": "Không đủ hàng",
        "errors": {"stock": "0"},
    }


def test_half_up_rounding():
    assert quantize_money("2.005") == Decimal("2.01")
    assert quantize_money("2.004") == Decimal("2.00")


def test_no_float_money():
    with pytest.raises(TypeError):
        quantize_money(2.005)


def test_weighted_average_import():
    assert weighted_average_cost(10, "5000000", 5, "5500000") == Decimal("5166666.67")


def test_weighted_average_restore():
    assert weighted_average_cost(5, "6000000", 1, "5000000") == Decimal("5833333.33")


def test_weighted_average_when_stock_zero():
    assert weighted_average_cost(0, "0", 5, "5500000") == Decimal("5500000.00")


def test_weighted_average_invalid_quantity():
    with pytest.raises(ValueError):
        weighted_average_cost(-1, "5000000", 1, "5000000")
    with pytest.raises(ValueError):
        weighted_average_cost(5, "5000000", 0, "5000000")


def test_system_clock_utc_naive():
    result = SystemClock().now_utc()
    assert result.tzinfo is None
    assert abs((datetime.now(UTC).replace(tzinfo=None) - result).total_seconds()) < 5


def test_fixed_clock_rejects_naive_datetime():
    with pytest.raises(ValueError):
        FixedClock(datetime(2026, 11, 4, 10, 0))


def test_fixed_clocks_are_independent():
    a = FixedClock(datetime(2026, 11, 4, 10, 0, tzinfo=UTC))
    b = FixedClock(datetime(2026, 11, 5, 10, 0, tzinfo=UTC))
    a.set_time(datetime(2026, 11, 4, 11, 0, tzinfo=UTC))
    assert a.now_utc() == datetime(2026, 11, 4, 11, 0)
    assert b.now_utc() == datetime(2026, 11, 5, 10, 0)


def test_service_injected_clock():
    clock = FixedClock(datetime(2026, 11, 4, 10, 0, tzinfo=UTC))
    service = BaseService(clock=clock)
    assert service.current_time() == datetime(2026, 11, 4, 10, 0)


def test_vietnam_timezone_date_shift():
    assert utc_to_vn(datetime(2026, 11, 4, 17, 30)).strftime("%Y-%m-%d %H:%M") == "2026-11-05 00:30"


def test_codes_from_ids():
    assert generate_code("order", 123) == "DH00000123"
    assert generate_code("import_receipt", 45) == "PN00000045"
    assert generate_code("invoice", 89) == "HD00000089"
    assert generate_code("stock_adjustment", 7) == "DC00000007"


def test_unique_temporary_codes():
    assert generate_temp_code() != generate_temp_code()


def test_code_rejects_bad_id():
    with pytest.raises(ValueError):
        generate_code("order", 0)
