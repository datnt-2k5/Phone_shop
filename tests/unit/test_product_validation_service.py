
"""Task 27: unit tests for SKU and variant validation."""

import pytest
from sqlalchemy.exc import IntegrityError

from models.app_error import AppError
from services.product_validation_service import (
    ProductIdentity,
    ProductValidationService,
)


class FakeProductRepository:
    def __init__(self):
        self.products = [
            {
                "id": 1,
                "sku": "P-001",
                "brand_id": 3,
                "name": "Phone A",
                "storage": "128GB",
                "color": "Black",
            },
            {
                "id": 2,
                "sku": "P-002",
                "brand_id": 3,
                "name": "Phone B",
                "storage": "128GB",
                "color": "Black",
            },
        ]

        self.calls = []

    def get_by_sku(self, sku):
        self.calls.append(("sku", sku))

        return next(
            (
                row
                for row in self.products
                if row["sku"].casefold() == sku.casefold()
            ),
            None,
        )

    def get_by_id(self, product_id, *, for_update=False):
        self.calls.append(
            ("id", product_id, for_update)
        )

        return next(
            (
                row
                for row in self.products
                if row["id"] == product_id
            ),
            None,
        )

    def find_variant(
        self,
        *,
        brand_id,
        name,
        storage,
        color,
        exclude_id=None,
    ):
        self.calls.append(
            (
                "variant",
                brand_id,
                name,
                storage,
                color,
                exclude_id,
            )
        )

        return next(
            (
                row
                for row in self.products
                if (
                    row["brand_id"] == brand_id
                    and row["name"].casefold() == name.casefold()
                    and row["storage"].casefold()
                    == storage.casefold()
                    and row["color"].casefold()
                    == color.casefold()
                    and row["id"] != exclude_id
                )
            ),
            None,
        )


@pytest.fixture
def repo():
    return FakeProductRepository()


def proposed(**overrides):
    return {
        "sku": "P-NEW",
        "brand_id": 3,
        "name": "Phone C",
        "storage": "256GB",
        "color": "White",
    } | overrides


def test_new_identity_valid_and_normalized(repo):
    result = ProductValidationService().validate_create(
        repo,
        **proposed(
            sku="  P-NEW  ",
            name="  Phone   C  ",
            storage=" 256GB ",
            color=" White ",
        ),
    )

    assert result == ProductIdentity(
        "P-NEW",
        3,
        "Phone C",
        "256GB",
        "White",
    )

    assert repo.calls == [
        ("sku", "P-NEW"),
        (
            "variant",
            3,
            "Phone C",
            "256GB",
            "White",
            None,
        ),
    ]


def test_duplicate_sku_rejected_before_variant_lookup(repo):
    with pytest.raises(AppError) as caught:
        ProductValidationService().validate_create(
            repo,
            **proposed(sku="p-001"),
        )

    assert caught.value.error_code == "PRODUCT_EXISTS"
    assert "sku" in caught.value.errors
    assert len(repo.calls) == 1


def test_duplicate_variant_rejected_even_with_new_sku(repo):
    with pytest.raises(AppError) as caught:
        ProductValidationService().validate_create(
            repo,
            **proposed(
                name="Phone A",
                storage="128GB",
                color="Black",
            ),
        )

    assert caught.value.error_code == "PRODUCT_EXISTS"
    assert "name" in caught.value.errors


@pytest.mark.parametrize(
    "change",
    [
        {"brand_id": 4},
        {"storage": "256GB"},
        {"color": "Gold"},
        {"name": "Phone X"},
    ],
)
def test_distinct_variant_is_allowed(repo, change):
    data = proposed(
        name="Phone A",
        storage="128GB",
        color="Black",
    ) | change

    identity = ProductValidationService().validate_create(
        repo,
        **data,
    )

    assert identity.sku == "P-NEW"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sku", ""),
        ("sku", "   "),
        ("sku", "x" * 51),
        ("sku", None),
        ("name", "  "),
        ("name", "N" * 151),
        ("storage", ""),
        ("storage", "s" * 51),
        ("color", ""),
        ("color", "c" * 51),
        ("brand_id", 0),
        ("brand_id", -2),
        ("brand_id", True),
        ("brand_id", "3"),
    ],
)
def test_invalid_input_is_rejected_before_database(
    repo,
    field,
    value,
):
    with pytest.raises(AppError) as caught:
        ProductValidationService().validate_create(
            repo,
            **proposed(**{field: value}),
        )

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert field in caught.value.errors
    assert repo.calls == []


def test_rename_unique_name_returns_normalized_name(repo):
    name = ProductValidationService().validate_rename(
        repo,
        product_id=1,
        new_name="  A   Plus  ",
    )

    assert name == "A Plus"
    assert repo.calls[0] == ("id", 1, True)
    assert repo.calls[1] == (
        "variant",
        3,
        "A Plus",
        "128GB",
        "Black",
        1,
    )


def test_rename_to_same_name_does_not_collide_with_self(repo):
    assert ProductValidationService().validate_rename(
        repo,
        product_id=1,
        new_name="Phone A",
    ) == "Phone A"


def test_rename_collision_rejected(repo):
    with pytest.raises(AppError) as caught:
        ProductValidationService().validate_rename(
            repo,
            product_id=1,
            new_name="Phone B",
        )

    assert caught.value.error_code == "PRODUCT_EXISTS"
    assert repo.calls[-1][-1] == 1


def test_rename_missing_product_is_not_found(repo):
    with pytest.raises(AppError) as caught:
        ProductValidationService().validate_rename(
            repo,
            product_id=99,
            new_name="New",
        )

    assert caught.value.error_code == "NOT_FOUND"
    assert len(repo.calls) == 1


@pytest.mark.parametrize(
    ("product_id", "name", "field"),
    [
        (0, "A", "product_id"),
        (True, "A", "product_id"),
        (1, "", "name"),
        (1, "X" * 151, "name"),
    ],
)
def test_rename_rejects_invalid_inputs(
    repo,
    product_id,
    name,
    field,
):
    with pytest.raises(AppError) as caught:
        ProductValidationService().validate_rename(
            repo,
            product_id=product_id,
            new_name=name,
        )

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert field in caught.value.errors
    assert repo.calls == []


def fake_integrity(code, detail):
    return IntegrityError(
        "INSERT INTO products ...",
        {},
        Exception(code, detail),
    )


@pytest.mark.parametrize(
    ("constraint", "field"),
    [
        ("uq_products_sku", "sku"),
        ("uq_products_variant", "name"),
    ],
)
def test_unique_1062_mapped_to_product_exists_without_sql_leak(
    constraint,
    field,
):
    raw = (
        "Duplicate entry 'secret-sku' "
        f"for key '{constraint}'"
    )

    error = ProductValidationService.translate_unique_error(
        fake_integrity(1062, raw)
    )

    assert error.error_code == "PRODUCT_EXISTS"
    assert field in error.errors
    assert "secret-sku" not in error.message


@pytest.mark.parametrize(
    ("code", "message"),
    [
        (1452, "foreign key failed"),
        (1062, "other_table_constraint"),
    ],
)
def test_other_integrity_errors_are_not_mislabeled(
    code,
    message,
):
    error = ProductValidationService.translate_unique_error(
        fake_integrity(code, message)
    )

    assert error is None
