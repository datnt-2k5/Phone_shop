
"""Task 33: no-DB contracts for BrandRepository and SupplierRepository."""

from datetime import datetime

import pytest

from repositories.brand_repository import BrandRepository
from repositories.supplier_repository import SupplierRepository

NOW = datetime(2026, 11, 10, 7, 0)


class FakeResult:
    def __init__(self, *, row=None, rows=None, lastrowid=17, rowcount=1):
        self.row = row
        self.rows = rows if rows is not None else []
        self.lastrowid = lastrowid
        self.rowcount = rowcount

    def mappings(self):
        return self

    def first(self):
        return self.row

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, result=None):
        self.result = result if result is not None else FakeResult()
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql.text, params))
        return self.result


def test_brand_create_uses_parameters_not_string_interpolation():
    session = FakeSession()
    name = "Brand'; DROP TABLE brands; --"
    assert BrandRepository(session).create(name=name, now_utc=NOW) == 17
    sql, params = session.calls[0]
    assert "INSERT INTO brands" in sql
    assert name not in sql
    assert params == {"name": name, "now_utc": NOW}


def test_brand_create_without_lastrowid_fails():
    session = FakeSession(FakeResult(lastrowid=None))
    with pytest.raises(RuntimeError, match="ID hãng"):
        BrandRepository(session).create(name="A", now_utc=NOW)


def test_brand_find_by_name_uses_database_collation():
    session = FakeSession(FakeResult(row={"id": 5, "name": "Apple"}))
    assert BrandRepository(session).find_by_name("apple") == {
        "id": 5, "name": "Apple"
    }
    sql, params = session.calls[0]
    assert "name = :name" in sql
    assert params == {"name": "apple"}


def test_brand_find_by_name_can_exclude_itself():
    session = FakeSession()
    assert BrandRepository(session).find_by_name("A", exclude_id=9) is None
    sql, params = session.calls[0]
    assert "id <> :exclude_id" in sql
    assert params == {"name": "A", "exclude_id": 9}


def test_brand_get_by_id_supports_row_lock():
    session = FakeSession(FakeResult(row={"id": 2}))
    assert BrandRepository(session).get_by_id(2, for_update=True) == {"id": 2}
    sql, params = session.calls[0]
    assert sql.rstrip().endswith("FOR UPDATE")
    assert params == {"brand_id": 2}


def test_brand_get_missing_returns_none():
    assert BrandRepository(FakeSession()).get_by_id(999) is None


def test_brand_list_is_paginated_and_sorted():
    session = FakeSession(FakeResult(rows=[{"id": 1}, {"id": 3}]))
    assert BrandRepository(session).list_brands(limit=2, offset=1) == [
        {"id": 1}, {"id": 3}
    ]
    sql, params = session.calls[0]
    assert "ORDER BY name ASC, id ASC" in sql
    assert params == {"limit": 2, "offset": 1}


@pytest.mark.parametrize(
    "limit,offset",
    [
        (0, 0),
        (101, 0),
        (True, 0),
        (5, -1),
        (5, True),
        (5, 1.5),
    ],
)
def test_invalid_brand_pagination_runs_no_sql(limit, offset):
    session = FakeSession()
    with pytest.raises(ValueError):
        BrandRepository(session).list_brands(limit=limit, offset=offset)
    assert session.calls == []


def test_brand_rename_does_not_change_products_or_creation_time():
    session = FakeSession()
    assert BrandRepository(session).update_name(brand_id=7, name="New")
    sql, params = session.calls[0]
    assert "UPDATE brands SET name = :name" in sql
    assert "created_at =" not in sql
    assert "DELETE" not in sql.upper()
    assert params == {"brand_id": 7, "name": "New"}


def test_brand_update_missing_returns_false():
    session = FakeSession(FakeResult(rowcount=0))
    assert not BrandRepository(session).update_name(brand_id=999, name="N")


def test_supplier_create_is_active_and_parameterized():
    session = FakeSession()
    result = SupplierRepository(session).create(
        name="Supplier",
        phone="0912345678",
        email="a@example.test",
        address="HN",
    )
    assert result == 17
    sql, params = session.calls[0]
    assert "INSERT INTO suppliers" in sql
    assert ":address, 1" in sql
    assert "is_active" not in params
    assert params["name"] == "Supplier"


def test_supplier_create_missing_lastrowid_fails():
    session = FakeSession(FakeResult(lastrowid=None))
    with pytest.raises(RuntimeError, match="ID nhà cung cấp"):
        SupplierRepository(session).create(name="Supplier")


def test_supplier_get_by_id_supports_row_lock():
    session = FakeSession(FakeResult(row={"id": 4, "is_active": 1}))
    assert SupplierRepository(session).get_by_id(4, for_update=True)["id"] == 4
    sql, params = session.calls[0]
    assert sql.rstrip().endswith("FOR UPDATE")
    assert params == {"supplier_id": 4}


def test_supplier_get_missing_returns_none():
    assert SupplierRepository(FakeSession()).get_by_id(888) is None


@pytest.mark.parametrize(
    "active,expected",
    [
        (None, None),
        (True, 1),
        (False, 0),
    ],
)
def test_supplier_list_filters_status(active, expected):
    session = FakeSession(FakeResult(rows=[{"id": 3}]))
    assert SupplierRepository(session).list_suppliers(
        is_active=active
    ) == [{"id": 3}]
    sql, params = session.calls[0]
    if expected is None:
        assert "WHERE is_active" not in sql
        assert "is_active" not in params
    else:
        assert "WHERE is_active = :is_active" in sql
        assert params["is_active"] == expected


@pytest.mark.parametrize("active", [1, "true", [], 0])
def test_supplier_list_rejects_invalid_status(active):
    session = FakeSession()
    with pytest.raises(ValueError):
        SupplierRepository(session).list_suppliers(is_active=active)
    assert session.calls == []


@pytest.mark.parametrize(
    "limit,offset",
    [
        (0, 0),
        (101, 0),
        (1, -1),
        (True, 0),
    ],
)
def test_supplier_invalid_pagination_runs_no_sql(limit, offset):
    session = FakeSession()
    with pytest.raises(ValueError):
        SupplierRepository(session).list_suppliers(
            limit=limit, offset=offset
        )
    assert session.calls == []


def test_supplier_update_details_does_not_change_status():
    session = FakeSession()
    assert SupplierRepository(session).update_details(
        supplier_id=2,
        name="Changed",
        phone=None,
        email=None,
        address="New location",
    )
    sql, params = session.calls[0]
    assert "SET name = :name" in sql
    assert "is_active =" not in sql
    assert "DELETE" not in sql.upper()
    assert params["supplier_id"] == 2


def test_supplier_update_missing_returns_false():
    session = FakeSession(FakeResult(rowcount=0))
    assert not SupplierRepository(session).update_details(
        supplier_id=999,
        name="None",
        phone=None,
        email=None,
        address=None,
    )
