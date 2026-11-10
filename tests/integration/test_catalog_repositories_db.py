
"""Task 33: Brand/Supplier Repository integration on phone_shop_test only."""

from datetime import datetime
from secrets import token_hex

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from repositories.brand_repository import BrandRepository
from repositories.supplier_repository import SupplierRepository

NOW = datetime(2026, 11, 10, 8, 0)  # UTC in database DATETIME.


@pytest.fixture
def ws(test_db: Connection):
    assert test_db.execute(
        text("SELECT DATABASE()")
    ).scalar_one() == "phone_shop_test"

    def factory():
        return Session(
            bind=test_db,
            join_transaction_mode="create_savepoint",
        )

    return {"db": test_db, "factory": factory}


def brand_name():
    return f"Task33 Brand {token_hex(7)}"


def supplier_name():
    return f"Task33 Supplier {token_hex(7)}"


def create_brand(ws, name):
    with ws["factory"]() as session, session.begin():
        return BrandRepository(session).create(
            name=name,
            now_utc=NOW,
        )


def create_supplier(ws, name):
    with ws["factory"]() as session, session.begin():
        return SupplierRepository(session).create(
            name=name,
            phone="0912345678",
            email="supplier@example.test",
            address="Địa chỉ kiểm thử",
        )


def test_existing_catalog_tables_have_required_columns(ws):
    for table, required in (
        ("brands", {"id", "name", "created_at"}),
        (
            "suppliers",
            {"id", "name", "phone", "email", "address", "is_active"},
        ),
    ):
        names = {
            row["column_name"]
            for row in ws["db"].execute(
                text("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = DATABASE() AND table_name = :table
                """),
                {"table": table},
            ).mappings()
        }
        assert required <= names


def test_create_brand_and_get_by_id(ws):
    name = brand_name()
    brand_id = create_brand(ws, name)

    with ws["factory"]() as session:
        row = BrandRepository(session).get_by_id(brand_id)

    assert row["id"] == brand_id
    assert row["name"] == name
    assert row["created_at"] == NOW


def test_brand_unique_name_enforced_at_database(ws):
    name = brand_name()
    original = create_brand(ws, name)

    with (
        pytest.raises(IntegrityError),
        ws["factory"]() as session,
        session.begin(),
    ):
        BrandRepository(session).create(
            name=name,
            now_utc=NOW,
        )

    with ws["factory"]() as session:
        assert BrandRepository(
            session
        ).find_by_name(name)["id"] == original


def test_brand_name_is_case_insensitive_by_existing_collation(ws):
    name = brand_name()
    create_brand(ws, name)

    with ws["factory"]() as session:
        assert BrandRepository(
            session
        ).find_by_name(name.lower()) is not None

    with (
        pytest.raises(IntegrityError),
        ws["factory"]() as session,
        session.begin(),
    ):
        BrandRepository(session).create(
            name=name.lower(),
            now_utc=NOW,
        )


def test_brand_rename_to_existing_name_is_rolled_back(ws):
    first_name = brand_name()
    second_name = brand_name()

    first_id = create_brand(ws, first_name)
    create_brand(ws, second_name)

    with (
        pytest.raises(IntegrityError),
        ws["factory"]() as session,
        session.begin(),
    ):
        BrandRepository(session).update_name(
            brand_id=first_id,
            name=second_name,
        )

    with ws["factory"]() as session:
        assert BrandRepository(
            session
        ).get_by_id(first_id)["name"] == first_name


def test_rename_brand_and_exclude_itself(ws):
    name = brand_name()
    brand_id = create_brand(ws, name)

    with ws["factory"]() as session, session.begin():
        repo = BrandRepository(session)

        assert repo.find_by_name(
            name,
            exclude_id=brand_id,
        ) is None

        assert repo.update_name(
            brand_id=brand_id,
            name=name + " New",
        )

    with ws["factory"]() as session:
        row = BrandRepository(session).get_by_id(brand_id)

    assert row["name"] == name + " New"
    assert row["created_at"] == NOW


def test_list_brands_contains_new_brand(ws):
    brand_id = create_brand(ws, brand_name())

    with ws["factory"]() as session:
        rows = BrandRepository(session).list_brands(
            limit=100
        )

    assert any(row["id"] == brand_id for row in rows)


def test_unknown_brand_update_does_not_write(ws):
    with ws["factory"]() as session, session.begin():
        assert BrandRepository(
            session
        ).get_by_id(-100) is None

        assert not BrandRepository(session).update_name(
            brand_id=-100,
            name="No",
        )


def test_brand_insert_rolls_back_on_caller_failure(ws):
    name = brand_name()

    with (
        pytest.raises(RuntimeError, match="test rollback"),
        ws["factory"]() as session,
        session.begin(),
    ):
        BrandRepository(session).create(
            name=name,
            now_utc=NOW,
        )
        raise RuntimeError("test rollback")

    with ws["factory"]() as session:
        assert BrandRepository(
            session
        ).find_by_name(name) is None


def test_create_supplier_starts_active(ws):
    name = supplier_name()
    supplier_id = create_supplier(ws, name)

    with ws["factory"]() as session:
        record = SupplierRepository(
            session
        ).get_by_id(supplier_id)

    assert record["id"] == supplier_id
    assert record["name"] == name
    assert bool(record["is_active"]) is True
    assert record["phone"] == "0912345678"
    assert record["email"] == "supplier@example.test"


def test_supplier_update_only_contact_fields(ws):
    supplier_id = create_supplier(ws, supplier_name())

    with ws["factory"]() as session, session.begin():
        assert SupplierRepository(session).update_details(
            supplier_id=supplier_id,
            name="Supplier Updated " + token_hex(5),
            phone="0987654321",
            email="updated@example.test",
            address="New address",
        )

    with ws["factory"]() as session:
        record = SupplierRepository(
            session
        ).get_by_id(supplier_id)

    assert record["phone"] == "0987654321"
    assert record["email"] == "updated@example.test"
    assert record["address"] == "New address"
    assert bool(record["is_active"]) is True


def test_supplier_list_filters_active_and_inactive(ws):
    active_id = create_supplier(ws, supplier_name())
    inactive_id = create_supplier(ws, supplier_name())

    # Chỉ tạo tình huống INACTIVE trong phone_shop_test.
    # Task 35 sẽ triển khai Service ngừng hợp tác.
    ws["db"].execute(
        text("""
            UPDATE suppliers SET is_active = 0
            WHERE id = :id
        """),
        {"id": inactive_id},
    )

    with ws["factory"]() as session:
        repo = SupplierRepository(session)
        active = repo.list_suppliers(is_active=True)
        inactive = repo.list_suppliers(is_active=False)

    assert active_id in {
        item["id"] for item in active
    }
    assert inactive_id not in {
        item["id"] for item in active
    }
    assert inactive_id in {
        item["id"] for item in inactive
    }
    assert active_id not in {
        item["id"] for item in inactive
    }


def test_supplier_details_edit_preserves_inactive_flag(ws):
    supplier_id = create_supplier(ws, supplier_name())

    ws["db"].execute(
        text("""
            UPDATE suppliers SET is_active = 0
            WHERE id = :id
        """),
        {"id": supplier_id},
    )

    with ws["factory"]() as session, session.begin():
        assert SupplierRepository(session).update_details(
            supplier_id=supplier_id,
            name=supplier_name(),
            phone=None,
            email=None,
            address=None,
        )

    with ws["factory"]() as session:
        row = SupplierRepository(
            session
        ).get_by_id(supplier_id)

    assert bool(row["is_active"]) is False


def test_supplier_unknown_id_is_not_found(ws):
    with ws["factory"]() as session, session.begin():
        repo = SupplierRepository(session)

        assert repo.get_by_id(-100) is None

        assert not repo.update_details(
            supplier_id=-100,
            name="Missing",
            phone=None,
            email=None,
            address=None,
        )


def test_supplier_duplicate_names_are_not_forced_unique(ws):
    # Task.md specifies UNIQUE for brands, not suppliers.
    name = supplier_name()
    first = create_supplier(ws, name)
    second = create_supplier(ws, name)

    assert first != second


def test_supplier_insert_rolls_back_on_caller_failure(ws):
    name = supplier_name()

    with (
        pytest.raises(RuntimeError, match="test rollback"),
        ws["factory"]() as session,
        session.begin(),
    ):
        SupplierRepository(session).create(name=name)
        raise RuntimeError("test rollback")

    with ws["factory"]() as session:
        matches = session.execute(
            text("""
                SELECT id FROM suppliers
                WHERE name = :name
            """),
            {"name": name},
        ).all()

    assert matches == []
