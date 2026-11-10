
"""US05 Task 26: ProductRepository integration tests on phone_shop_test."""

from datetime import datetime
from decimal import Decimal
from secrets import token_hex

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from repositories.product_repository import ProductRepository

NOW = datetime(2026, 11, 9, 9, 0)  # UTC stored as naive DATETIME.


@pytest.fixture
def workspace(test_db: Connection):
    """Only the test_db transaction; every test rolls back afterwards."""
    unique = token_hex(6)
    result = test_db.execute(
        text("""
            INSERT INTO brands (name, created_at)
            VALUES (:name, :now)
        """),
        {
            "name": f"Task26 Brand {unique}",
            "now": NOW,
        },
    )
    brand_id = int(result.lastrowid)

    def session_factory():
        return Session(
            bind=test_db,
            join_transaction_mode="create_savepoint",
        )

    return {
        "db": test_db,
        "brand_id": brand_id,
        "factory": session_factory,
    }


def product_data(
    ws,
    *,
    sku=None,
    name=None,
    storage="128GB",
    color="Black",
):
    tag = token_hex(6)
    return {
        "sku": sku or f"T26-{tag}",
        "name": name or f"Phone {tag}",
        "brand_id": ws["brand_id"],
        "storage": storage,
        "color": color,
        "sell_price": Decimal("12990000.00"),
        "min_stock": 3,
        "description": "Mô tả thử nghiệm",
        "image_url": None,
        "now_utc": NOW,
        "updated_by": None,
    }


def create(ws, values):
    with ws["factory"]() as session, session.begin():
        return ProductRepository(session).create(**values)


def read_admin(ws, product_id):
    with ws["factory"]() as session:
        return ProductRepository(session).get_by_id(product_id)


def test_create_product_sets_opening_inventory_and_status(workspace):
    values = product_data(workspace)
    product_id = create(workspace, values)
    record = read_admin(workspace, product_id)

    assert record["sku"] == values["sku"]
    assert record["name"] == values["name"]
    assert record["brand_id"] == workspace["brand_id"]
    assert record["storage"] == "128GB"
    assert record["color"] == "Black"
    assert record["sell_price"] == Decimal("12990000.00")
    assert record["cost_price"] == Decimal("0.00")
    assert record["stock"] == 0
    assert record["min_stock"] == 3
    assert record["status"] == "ACTIVE"


def test_find_product_by_sku_and_locked_id(workspace):
    values = product_data(workspace)
    product_id = create(workspace, values)

    with workspace["factory"]() as session, session.begin():
        repo = ProductRepository(session)
        assert repo.get_by_sku(values["sku"])["id"] == product_id
        assert repo.get_by_id(
            product_id,
            for_update=True,
        )["sku"] == values["sku"]


def test_find_variant_excludes_its_own_id(workspace):
    values = product_data(workspace)
    product_id = create(workspace, values)

    with workspace["factory"]() as session:
        repo = ProductRepository(session)
        matching = repo.find_variant(
            brand_id=values["brand_id"],
            name=values["name"],
            storage=values["storage"],
            color=values["color"],
        )
        excluding = repo.find_variant(
            brand_id=values["brand_id"],
            name=values["name"],
            storage=values["storage"],
            color=values["color"],
            exclude_id=product_id,
        )

    assert matching["id"] == product_id
    assert excluding is None


def test_public_view_hides_cost_and_exact_stock(workspace):
    product_id = create(
        workspace,
        product_data(workspace),
    )

    with workspace["factory"]() as session:
        repo = ProductRepository(session)
        public = repo.get_public_by_id(product_id)
        listed = repo.list_public()

    assert public["id"] == product_id
    assert "cost_price" not in public
    assert "stock" not in public
    assert "min_stock" not in public
    assert "in_stock" in public
    assert any(item["id"] == product_id for item in listed)
    assert all("cost_price" not in item for item in listed)
    assert all("stock" not in item for item in listed)


def test_update_details_does_not_change_inventory_or_identity(
    workspace,
):
    values = product_data(workspace)
    product_id = create(workspace, values)
    before = read_admin(workspace, product_id)

    with workspace["factory"]() as session, session.begin():
        changed = ProductRepository(session).update_details(
            product_id=product_id,
            name="New display name",
            sell_price=Decimal("12500000.00"),
            min_stock=9,
            description="Updated",
            image_url="/images/phone.png",
            now_utc=NOW,
            updated_by=None,
        )

    after = read_admin(workspace, product_id)
    assert changed is True
    assert after["name"] == "New display name"
    assert after["sell_price"] == Decimal("12500000.00")
    assert after["min_stock"] == 9
    assert after["image_url"] == "/images/phone.png"

    for field in (
        "sku",
        "brand_id",
        "storage",
        "color",
        "stock",
        "cost_price",
    ):
        assert after[field] == before[field]


def test_discontinue_then_restore_keeps_product_row(workspace):
    product_id = create(
        workspace,
        product_data(workspace),
    )

    with workspace["factory"]() as session, session.begin():
        assert ProductRepository(session).set_status(
            product_id=product_id,
            status="DISCONTINUED",
            now_utc=NOW,
            updated_by=None,
        )

    with workspace["factory"]() as session:
        repo = ProductRepository(session)
        assert repo.get_by_id(
            product_id
        )["status"] == "DISCONTINUED"
        assert repo.get_public_by_id(product_id) is None
        assert all(
            row["id"] != product_id
            for row in repo.list_public()
        )

    with workspace["factory"]() as session, session.begin():
        assert ProductRepository(session).set_status(
            product_id=product_id,
            status="ACTIVE",
            now_utc=NOW,
            updated_by=None,
        )

    with workspace["factory"]() as session:
        assert ProductRepository(
            session
        ).get_public_by_id(product_id) is not None


def test_unknown_product_returns_none_and_updates_false(workspace):
    with workspace["factory"]() as session, session.begin():
        repo = ProductRepository(session)

        assert repo.get_by_id(-999) is None
        assert repo.get_by_sku("T26-UNKNOWN") is None

        assert not repo.update_details(
            product_id=-999,
            name="X",
            sell_price=Decimal("10.00"),
            min_stock=0,
            description=None,
            image_url=None,
            now_utc=NOW,
            updated_by=None,
        )

        assert not repo.set_status(
            product_id=-999,
            status="DISCONTINUED",
            now_utc=NOW,
            updated_by=None,
        )


def test_unique_sku_enforced_by_database(workspace):
    first = product_data(workspace)
    create(workspace, first)

    second = product_data(
        workspace,
        sku=first["sku"],
    )

    with (
        pytest.raises(IntegrityError),
        workspace["factory"]() as session,
        session.begin(),
    ):
        ProductRepository(session).create(**second)

    with workspace["factory"]() as session:
        assert ProductRepository(
            session
        ).get_by_sku(first["sku"]) is not None


def test_unique_variant_enforced_by_database(workspace):
    first = product_data(workspace)
    create(workspace, first)

    duplicate_variant = product_data(
        workspace,
        name=first["name"],
    )

    with (
        pytest.raises(IntegrityError),
        workspace["factory"]() as session,
        session.begin(),
    ):
        ProductRepository(session).create(**duplicate_variant)


def test_nonpositive_price_rejected_by_database_constraint(workspace):
    values = product_data(workspace)
    values["sell_price"] = Decimal("0.00")

    with (
        pytest.raises(DBAPIError),
        workspace["factory"]() as session,
        session.begin(),
    ):
        ProductRepository(session).create(**values)


def test_invalid_brand_rejected_by_fk(workspace):
    values = product_data(workspace)
    values["brand_id"] = 99999999999999

    with (
        pytest.raises(IntegrityError),
        workspace["factory"]() as session,
        session.begin(),
    ):
        ProductRepository(session).create(**values)


def test_repository_does_not_commit_outside_caller_transaction(
    workspace,
):
    values = product_data(workspace)

    with (
        pytest.raises(RuntimeError, match="rollback test"),
        workspace["factory"]() as session,
        session.begin(),
    ):
        ProductRepository(session).create(**values)
        raise RuntimeError("rollback test")

    with workspace["factory"]() as session:
        assert ProductRepository(
            session
        ).get_by_sku(values["sku"]) is None


def test_admin_list_pagination_returns_latest_first(workspace):
    first = create(
        workspace,
        product_data(workspace),
    )
    second = create(
        workspace,
        product_data(workspace),
    )

    with workspace["factory"]() as session:
        repo = ProductRepository(session)
        first_page = repo.list_products(
            limit=1,
            offset=0,
        )
        next_page = repo.list_products(
            limit=1,
            offset=1,
        )

    assert first_page[0]["id"] == second
    assert next_page[0]["id"] == first
