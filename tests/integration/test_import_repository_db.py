
"""Task 37: Import Repository integration tests on MariaDB."""

from datetime import datetime
from decimal import Decimal
from secrets import token_hex

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from repositories.brand_repository import BrandRepository
from repositories.import_repository import ImportRepository
from repositories.product_repository import ProductRepository
from repositories.supplier_repository import SupplierRepository
from services.auth_service import AuthService

NOW = datetime(2026, 11, 10, 13, 0, 0)
PASSWORD = "MatKhau123!"


@pytest.fixture
def env(test_db: Connection):
    """Prepare isolated records; test_db rolls back all writes."""
    assert test_db.execute(
        text("SELECT DATABASE()")
    ).scalar_one() == "phone_shop_test"

    def factory():
        return Session(
            bind=test_db,
            join_transaction_mode="create_savepoint",
        )

    auth = AuthService(session_factory=factory)
    user = auth.register(
        email=f"t37_{token_hex(7)}@example.test",
        password=PASSWORD,
        confirm_password=PASSWORD,
        full_name="Task 37 Tester",
        phone="0912345678",
    )

    with factory() as session, session.begin():
        brand_id = BrandRepository(session).create(
            name=f"T37 Brand {token_hex(7)}",
            now_utc=NOW,
        )
        supplier_id = SupplierRepository(session).create(
            name=f"T37 Supplier {token_hex(7)}",
        )
        product_id = ProductRepository(session).create(
            sku=f"T37-{token_hex(6)}",
            name=f"T37 Phone {token_hex(6)}",
            brand_id=brand_id,
            storage="128GB",
            color="Black",
            sell_price=Decimal("8000000.00"),
            now_utc=NOW,
        )

    return {
        "factory": factory,
        "user_id": user.user_id,
        "supplier_id": supplier_id,
        "product_id": product_id,
    }


def make_receipt(repo, env, *, suffix="A"):
    return repo.create_receipt(
        temporary_code=f"TMP-T37-{suffix}-{token_hex(6)}",
        supplier_id=env["supplier_id"],
        import_date=NOW,
        total_amount=Decimal("5000000.00"),
        note="Integration test",
        created_by=env["user_id"],
        created_at=NOW,
    )


def make_item(repo, env, receipt_id):
    return repo.create_item(
        receipt_id=receipt_id,
        product_id=env["product_id"],
        quantity=2,
        import_price=Decimal("2500000.00"),
        line_total=Decimal("5000000.00"),
    )


def test_receipt_and_item_round_trip(env):
    with env["factory"]() as session, session.begin():
        repo = ImportRepository(session)
        receipt_id = make_receipt(repo, env)
        official_code = f"PN{receipt_id:08d}"

        assert repo.update_code(
            receipt_id=receipt_id,
            code=official_code,
        )

        item_id = make_item(repo, env, receipt_id)
        assert item_id > 0

    with env["factory"]() as session:
        repo = ImportRepository(session)
        receipt = repo.get_receipt(receipt_id)
        items = repo.list_items(receipt_id)

        assert receipt is not None
        assert receipt["code"] == official_code
        assert receipt["supplier_id"] == env["supplier_id"]
        assert receipt["total_amount"] == Decimal("5000000.00")

        assert len(items) == 1
        assert items[0]["product_id"] == env["product_id"]
        assert items[0]["quantity"] == 2
        assert items[0]["line_total"] == Decimal("5000000.00")

        listed = repo.list_receipts(limit=100, offset=0)
        assert any(row["id"] == receipt_id for row in listed)


def test_duplicate_item_is_rejected_without_losing_first(env):
    with env["factory"]() as session, session.begin():
        repo = ImportRepository(session)
        receipt_id = make_receipt(repo, env)

        make_item(repo, env, receipt_id)

        with pytest.raises(IntegrityError), session.begin_nested():
            make_item(repo, env, receipt_id)

        items = repo.list_items(receipt_id)
        assert len(items) == 1
        assert items[0]["quantity"] == 2


def test_savepoint_rollback_removes_receipt_and_items(env):
    with env["factory"]() as session, session.begin():
        repo = ImportRepository(session)

        with session.begin_nested() as nested:
            receipt_id = make_receipt(repo, env)
            make_item(repo, env, receipt_id)

            assert repo.get_receipt(receipt_id) is not None
            assert len(repo.list_items(receipt_id)) == 1

            nested.rollback()

        assert repo.get_receipt(receipt_id) is None
        assert repo.list_items(receipt_id) == []


def test_receipts_pagination_uses_newest_first(env):
    with env["factory"]() as session, session.begin():
        repo = ImportRepository(session)

        first_id = make_receipt(repo, env, suffix="FIRST")
        make_item(repo, env, first_id)

        second_id = make_receipt(repo, env, suffix="SECOND")
        make_item(repo, env, second_id)

        assert second_id > first_id

        newest = repo.list_receipts(limit=1, offset=0)
        assert newest[0]["id"] == second_id
