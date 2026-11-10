
"""US05 Task 27: duplicate-validation tests on phone_shop_test."""

from datetime import datetime
from decimal import Decimal
from secrets import token_hex

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.app_error import AppError
from repositories.product_repository import ProductRepository
from services.product_validation_service import ProductValidationService

NOW = datetime(2026, 11, 10, 9, 0)


@pytest.fixture
def workspace(test_db: Connection):
    """Use the existing rollback fixture for phone_shop_test."""

    unique = token_hex(6)

    result = test_db.execute(
        text("""
            INSERT INTO brands (
                name,
                created_at
            )
            VALUES (
                :name,
                :now
            )
        """),
        {
            "name": f"Task27 Brand {unique}",
            "now": NOW,
        },
    )

    def factory():
        return Session(
            bind=test_db,
            join_transaction_mode="create_savepoint",
        )

    return {
        "db": test_db,
        "brand_id": int(result.lastrowid),
        "factory": factory,
    }


def sample(ws, **overrides):
    token = token_hex(6)

    return {
        "sku": f"T27-{token}",
        "brand_id": ws["brand_id"],
        "name": f"Model {token}",
        "storage": "128GB",
        "color": "Black",
    } | overrides


def write_product(repo, identity):
    """Insert using the normalized identity."""

    return repo.create(
        sku=identity.sku,
        brand_id=identity.brand_id,
        name=identity.name,
        storage=identity.storage,
        color=identity.color,
        sell_price=Decimal("12990000.00"),
        min_stock=2,
        now_utc=NOW,
        updated_by=None,
    )


def create_verified(ws, data):
    """Validate and insert in the SAME database transaction."""

    with ws["factory"]() as session, session.begin():
        repo = ProductRepository(session)

        identity = ProductValidationService().validate_create(
            repo,
            **data,
        )

        return write_product(repo, identity)


def create_without_precheck(ws, data):
    """Test ONLY: bypass validation to verify database constraints."""

    with ws["factory"]() as session, session.begin():
        return ProductRepository(session).create(
            **data,
            sell_price=Decimal("12990000.00"),
            now_utc=NOW,
            updated_by=None,
        )


def read(ws, product_id):
    with ws["factory"]() as session:
        return ProductRepository(session).get_by_id(
            product_id
        )


def rename_verified(ws, product_id, new_name):
    """Validate and update using one locked transaction."""

    with ws["factory"]() as session, session.begin():
        repo = ProductRepository(session)

        name = ProductValidationService().validate_rename(
            repo,
            product_id=product_id,
            new_name=new_name,
        )

        record = repo.get_by_id(product_id)

        return repo.update_details(
            product_id=product_id,
            name=name,
            sell_price=record["sell_price"],
            min_stock=record["min_stock"],
            description=record["description"],
            image_url=record["image_url"],
            now_utc=NOW,
            updated_by=None,
        )


def test_valid_create_normalizes_fields_and_persists(
    workspace,
):
    data = sample(
        workspace,
        sku=" T27-OK ",
        name="  Phone   Alpha ",
    )

    product_id = create_verified(workspace, data)
    record = read(workspace, product_id)

    assert record["sku"] == "T27-OK"
    assert record["name"] == "Phone Alpha"
    assert record["stock"] == 0
    assert record["cost_price"] == Decimal("0.00")


def test_same_sku_rejected_before_insert(workspace):
    first = sample(workspace, name="A")
    create_verified(workspace, first)

    second = sample(
        workspace,
        sku=first["sku"],
        name="B",
    )

    with pytest.raises(AppError) as caught:
        create_verified(workspace, second)

    assert caught.value.error_code == "PRODUCT_EXISTS"
    assert "sku" in caught.value.errors


def test_same_sku_different_case_rejected_by_db_collation(
    workspace,
):
    first = sample(workspace, name="A")
    create_verified(workspace, first)

    other = sample(
        workspace,
        sku=first["sku"].lower(),
        name="B",
    )

    with pytest.raises(AppError) as caught:
        create_verified(workspace, other)

    assert caught.value.error_code == "PRODUCT_EXISTS"


def test_duplicate_variant_with_other_sku_rejected(
    workspace,
):
    first = sample(
        workspace,
        name="Model Common",
    )
    create_verified(workspace, first)

    second = sample(
        workspace,
        name="Model Common",
    )

    with pytest.raises(AppError) as caught:
        create_verified(workspace, second)

    assert caught.value.error_code == "PRODUCT_EXISTS"
    assert "name" in caught.value.errors


def test_same_name_other_color_allowed(workspace):
    first = sample(
        workspace,
        name="Color Phone",
    )

    second = sample(
        workspace,
        name="Color Phone",
        color="White",
    )

    first_id = create_verified(workspace, first)
    second_id = create_verified(workspace, second)

    assert first_id != second_id


def test_rename_to_other_product_name_rejected_without_change(
    workspace,
):
    first_id = create_verified(
        workspace,
        sample(workspace, name="Phone One"),
    )

    create_verified(
        workspace,
        sample(workspace, name="Phone Two"),
    )

    before = read(workspace, first_id)

    with pytest.raises(AppError) as caught:
        rename_verified(
            workspace,
            first_id,
            "  Phone   Two  ",
        )

    assert caught.value.error_code == "PRODUCT_EXISTS"
    assert read(workspace, first_id) == before


def test_rename_to_own_name_is_allowed(workspace):
    product_id = create_verified(
        workspace,
        sample(workspace, name="Phone One"),
    )

    assert rename_verified(
        workspace,
        product_id,
        "Phone One",
    ) is True


def test_rename_unique_name_preserves_stock_cost_and_sku(
    workspace,
):
    product_id = create_verified(
        workspace,
        sample(workspace, name="Phone One"),
    )

    before = read(workspace, product_id)

    assert rename_verified(
        workspace,
        product_id,
        "  Phone  Premium  ",
    )

    after = read(workspace, product_id)

    assert after["name"] == "Phone Premium"

    for key in (
        "sku",
        "brand_id",
        "storage",
        "color",
        "stock",
        "cost_price",
    ):
        assert after[key] == before[key]


def test_rename_missing_product_returns_not_found(
    workspace,
):
    with pytest.raises(AppError) as caught:
        rename_verified(
            workspace,
            99999999999,
            "New Name",
        )

    assert caught.value.error_code == "NOT_FOUND"


def test_db_unique_sku_still_guards_bypassed_validation(
    workspace,
):
    first = sample(workspace, name="A")
    create_verified(workspace, first)

    second = sample(
        workspace,
        sku=first["sku"],
        name="B",
    )

    with pytest.raises(IntegrityError) as caught:
        create_without_precheck(workspace, second)

    error = ProductValidationService.translate_unique_error(
        caught.value
    )

    assert error is not None
    assert error.error_code == "PRODUCT_EXISTS"
    assert "sku" in error.errors


def test_db_unique_variant_still_guards_bypassed_validation(
    workspace,
):
    first = sample(
        workspace,
        name="Same Variant",
    )
    create_verified(workspace, first)

    second = sample(
        workspace,
        name="Same Variant",
    )

    with pytest.raises(IntegrityError) as caught:
        create_without_precheck(workspace, second)

    error = ProductValidationService.translate_unique_error(
        caught.value
    )

    assert error is not None
    assert error.error_code == "PRODUCT_EXISTS"
    assert "name" in error.errors


def test_db_unique_variant_guards_direct_rename(
    workspace,
):
    first_id = create_verified(
        workspace,
        sample(workspace, name="A"),
    )

    create_verified(
        workspace,
        sample(workspace, name="B"),
    )

    before = read(workspace, first_id)

    with (
        pytest.raises(IntegrityError) as caught,
        workspace["factory"]() as session,
        session.begin(),
    ):
        ProductRepository(session).update_details(
            product_id=first_id,
            name="B",
            sell_price=before["sell_price"],
            min_stock=before["min_stock"],
            description=before["description"],
            image_url=before["image_url"],
            now_utc=NOW,
            updated_by=None,
        )

    mapped = ProductValidationService.translate_unique_error(
        caught.value
    )

    assert mapped is not None
    assert mapped.error_code == "PRODUCT_EXISTS"
    assert read(workspace, first_id) == before


def test_fk_violation_is_not_mislabeled_as_duplicate(
    workspace,
):
    invalid = sample(
        workspace,
        brand_id=99999999999999,
    )

    with pytest.raises(IntegrityError) as caught:
        create_without_precheck(workspace, invalid)

    assert (
        ProductValidationService.translate_unique_error(
            caught.value
        )
        is None
    )
