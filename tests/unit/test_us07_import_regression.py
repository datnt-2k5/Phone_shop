
"""Task 41 / US07: regression tests for money, inputs and SQL contracts."""

from decimal import Decimal
from unittest.mock import Mock

import pytest

from models.app_error import AppError
from repositories.inventory_repository import InventoryRepository
from repositories.stock_movement_repository import StockMovementRepository
from services.import_service import ImportService
from utils.money_utils import quantize_money, weighted_average_cost


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1.005", "1.01"),
        ("1.004", "1.00"),
        ("1.015", "1.02"),
        ("1.025", "1.03"),
        ("-1.005", "-1.01"),
        ("0.005", "0.01"),
    ],
)
def test_round_half_up_at_exact_midpoint(value, expected):
    assert quantize_money(value) == Decimal(expected)


@pytest.mark.parametrize(
    ("old_qty", "old_cost", "add_qty", "add_cost", "expected"),
    [
        (0, "0.00", 1, "100.00", "100.00"),
        (10, "5000000.00", 5, "5500000.00", "5166666.67"),
        (1, "0.01", 1, "0.02", "0.02"),
        (1, "0.01", 1, "0.01", "0.01"),
        (2, "0.01", 1, "0.02", "0.01"),
        (3, "100.00", 1, "101.00", "100.25"),
    ],
)
def test_weighted_average_uses_decimal(
    old_qty, old_cost, add_qty, add_cost, expected
):
    result = weighted_average_cost(
        old_qty,
        Decimal(old_cost),
        add_qty,
        Decimal(add_cost),
    )

    assert result == Decimal(expected)
    assert isinstance(result, Decimal)


@pytest.mark.parametrize(
    ("old_qty", "add_qty"),
    [
        (-1, 1),
        (0, 0),
        (1, -1),
        (True, 1),
        (1, 1.5),
    ],
)
def test_weighted_average_rejects_invalid_quantities(
    old_qty, add_qty
):
    with pytest.raises(ValueError):
        weighted_average_cost(
            old_qty,
            Decimal("100.00"),
            add_qty,
            Decimal("100.00"),
        )


@pytest.mark.parametrize(
    "value",
    [
        1.5,
        True,
    ],
)
def test_money_conversion_rejects_float_and_bool(value):
    with pytest.raises(TypeError):
        quantize_money(value)


def test_prepare_sorts_products_and_calculates_total():
    supplier_id, lines, total, note = ImportService._prepare(
        supplier_id=7,
        items=[
            {
                "product_id": 9,
                "quantity": 3,
                "import_price": "200.00",
            },
            {
                "product_id": 2,
                "quantity": 2,
                "import_price": Decimal("100.50"),
            },
        ],
        note="  Nhập thử  ",
    )

    assert supplier_id == 7
    assert [row["product_id"] for row in lines] == [2, 9]
    assert total == Decimal("801.00")
    assert lines[0]["line_total"] == Decimal("201.00")
    assert lines[1]["line_total"] == Decimal("600.00")
    assert note == "Nhập thử"


@pytest.mark.parametrize(
    "price",
    [
        "0",
        "-1.00",
        "1.001",
        "NaN",
        "Infinity",
        "abc",
        1.5,
        True,
    ],
)
def test_prepare_rejects_invalid_prices(price):
    with pytest.raises(AppError) as caught:
        ImportService._prepare(
            supplier_id=1,
            items=[
                {
                    "product_id": 2,
                    "quantity": 1,
                    "import_price": price,
                }
            ],
            note=None,
        )

    assert caught.value.error_code == "VALIDATION_ERROR"


def test_prepare_rejects_duplicate_product():
    with pytest.raises(AppError) as caught:
        ImportService._prepare(
            supplier_id=1,
            items=[
                {
                    "product_id": 2,
                    "quantity": 1,
                    "import_price": "100.00",
                },
                {
                    "product_id": 2,
                    "quantity": 2,
                    "import_price": "200.00",
                },
            ],
            note=None,
        )

    assert caught.value.error_code == "VALIDATION_ERROR"


def test_prepare_rejects_amount_overflow():
    with pytest.raises(AppError) as caught:
        ImportService._prepare(
            supplier_id=1,
            items=[
                {
                    "product_id": 2,
                    "quantity": 2,
                    "import_price": "9999999999999999.99",
                }
            ],
            note=None,
        )

    assert caught.value.error_code == "VALIDATION_ERROR"


def test_inventory_query_uses_for_update():
    session = Mock()
    session.execute.return_value.mappings.return_value.first.return_value = {
        "id": 5,
        "stock": 3,
        "cost_price": Decimal("100.00"),
        "status": "ACTIVE",
    }

    result = InventoryRepository(session).get_for_update(5)

    sql, params = session.execute.call_args.args

    assert "FOR UPDATE" in sql.text.upper()
    assert ":product_id" in sql.text
    assert params == {"product_id": 5}
    assert result["stock"] == 3
    session.commit.assert_not_called()


def test_movement_operation_key_is_parameterized():
    session = Mock()
    session.execute.return_value.lastrowid = 99

    result = StockMovementRepository(session).record_import(
        receipt_id=10,
        product_id=5,
        quantity=3,
        stock_after=7,
        created_at=None,
        created_by=1,
    )

    sql, params = session.execute.call_args.args

    assert result == 99
    assert params["operation_key"] == "IMPORT:10:5"
    assert params["quantity"] == 3
    assert params["stock_after"] == 7
    assert ":operation_key" in sql.text
    assert "'IMPORT'" in sql.text

    session.commit.assert_not_called()
    session.rollback.assert_not_called()
