
"""Unit tests for Task 37 - US07-T01."""

from datetime import datetime
from decimal import Decimal
from unittest.mock import Mock

import pytest

from repositories.import_repository import ImportRepository

NOW = datetime(2026, 11, 10, 13, 0, 0)


def test_create_receipt_returns_id_without_commit():
    session = Mock()
    session.execute.return_value.lastrowid = 15
    repo = ImportRepository(session)

    result = repo.create_receipt(
        temporary_code="TMP-TEST-001",
        supplier_id=1,
        import_date=NOW,
        total_amount=Decimal("5000000.00"),
        note="Test",
        created_by=1,
        created_at=NOW,
    )

    assert result == 15
    sql, params = session.execute.call_args.args
    assert "INSERT INTO import_receipts" in str(sql)
    assert params["total_amount"] == Decimal("5000000.00")
    session.commit.assert_not_called()


def test_update_receipt_code():
    session = Mock()
    session.execute.return_value.rowcount = 1
    repo = ImportRepository(session)

    result = repo.update_code(
        receipt_id=15,
        code="PN00000015",
    )

    assert result is True
    params = session.execute.call_args.args[1]
    assert params["receipt_id"] == 15
    assert params["code"] == "PN00000015"
    session.commit.assert_not_called()


def test_create_item_returns_id():
    session = Mock()
    session.execute.return_value.lastrowid = 9
    repo = ImportRepository(session)

    result = repo.create_item(
        receipt_id=15,
        product_id=3,
        quantity=2,
        import_price=Decimal("2500000.00"),
        line_total=Decimal("5000000.00"),
    )

    assert result == 9
    session.commit.assert_not_called()


def test_get_receipt_returns_record():
    session = Mock()
    session.execute.return_value.mappings.return_value.first.return_value = {
        "id": 15,
        "code": "PN00000015",
    }
    repo = ImportRepository(session)

    result = repo.get_receipt(15)

    assert result["id"] == 15
    assert result["code"] == "PN00000015"


def test_get_missing_receipt_returns_none():
    session = Mock()
    session.execute.return_value.mappings.return_value.first.return_value = None
    repo = ImportRepository(session)

    assert repo.get_receipt(999) is None


def test_list_items_returns_rows():
    session = Mock()
    session.execute.return_value.mappings.return_value.all.return_value = [
        {"id": 1, "product_id": 3},
        {"id": 2, "product_id": 4},
    ]
    repo = ImportRepository(session)

    result = repo.list_items(15)

    assert len(result) == 2
    assert result[1]["product_id"] == 4


@pytest.mark.parametrize(
    "limit,offset",
    [(0, 0), (101, 0), (10, -1), (True, 0)],
)
def test_invalid_pagination_is_rejected(limit, offset):
    repo = ImportRepository(Mock())

    with pytest.raises(ValueError):
        repo.list_receipts(limit=limit, offset=offset)
