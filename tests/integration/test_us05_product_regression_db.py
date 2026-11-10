
"""Task 31: product regression tests on isolated phone_shop_test."""

from datetime import UTC, datetime
from decimal import Decimal
from secrets import token_hex

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from models.app_error import AppError
from repositories.product_repository import ProductRepository
from services.auth_service import AuthService
from services.product_create_service import ProductCreateService
from services.product_edit_service import ProductEditService
from services.product_management_service import ProductManagementService
from utils.time_utils import FixedClock

NOW = datetime(2026, 11, 10, 6, 0, tzinfo=UTC)
PASSWORD = "MatKhau123!"


class Store:
    """Session giả chỉ dành cho bài kiểm thử."""

    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value

    def remove(self, key):
        self.data.pop(key, None)


@pytest.fixture
def ws(test_db: Connection):
    """Tất cả dữ liệu nằm trong transaction của phone_shop_test."""

    assert test_db.execute(
        text("SELECT DATABASE()")
    ).scalar_one() == "phone_shop_test"

    def factory():
        return Session(
            bind=test_db,
            join_transaction_mode="create_savepoint",
        )

    brand = test_db.execute(
        text("""
            INSERT INTO brands (name, created_at)
            VALUES (:name, :created_at)
        """),
        {
            "name": f"Task31 Brand {token_hex(6)}",
            "created_at": NOW.replace(tzinfo=None),
        },
    )

    auth = AuthService(session_factory=factory)
    accounts = {}

    for role in ("admin", "customer"):
        email = (
            f"task31_{role}_{token_hex(8)}@example.test"
        )

        registered = auth.register(
            email=email,
            password=PASSWORD,
            confirm_password=PASSWORD,
            full_name=f"Task31 {role}",
            phone="0912345678",
        )

        accounts[role] = {
            "id": registered.user_id,
            "email": email,
            "store": Store(),
        }

    # Chỉ đổi quyền tài khoản vừa tạo trong phone_shop_test.
    test_db.execute(
        text("""
            UPDATE users
            SET role = 'ADMIN'
            WHERE id = :user_id
        """),
        {"user_id": accounts["admin"]["id"]},
    )

    for account in accounts.values():
        auth.login(
            email=account["email"],
            password=PASSWORD,
            session_store=account["store"],
        )

    return {
        "db": test_db,
        "factory": factory,
        "brand_id": int(brand.lastrowid),
        "admin": accounts["admin"],
        "customer": accounts["customer"],
        "creator": ProductCreateService(
            session_factory=factory,
            auth_service=auth,
            clock=FixedClock(NOW),
        ),
        "editor": ProductEditService(
            session_factory=factory,
            auth_service=auth,
            clock=FixedClock(NOW),
        ),
        "management": ProductManagementService(
            session_factory=factory,
            auth_service=auth,
            clock=FixedClock(NOW),
        ),
    }


def create_values(ws, **changes):
    return {
        "session_store": ws["admin"]["store"],
        "sku": f"T31-{token_hex(7)}",
        "name": f"Phone {token_hex(7)}",
        "brand_id": ws["brand_id"],
        "storage": "128GB",
        "color": "Black",
        "sell_price": "12500000",
        "min_stock": 3,
        "description": "Sản phẩm kiểm thử",
        "image_url": None,
    } | changes


def create(ws, **changes):
    return ws["creator"].create(
        **create_values(ws, **changes)
    )


def read(ws, product_id):
    with ws["factory"]() as session:
        return ProductRepository(session).get_by_id(
            product_id
        )


def edit_values(ws, product_id, **changes):
    return {
        "session_store": ws["admin"]["store"],
        "product_id": product_id,
        "name": "Phone Edited",
        "description": "Mô tả sau cập nhật",
        "sell_price": "13500000",
        "image_url": "/images/task31.png",
        "min_stock": 5,
    } | changes


def test_stock01_new_product_starts_zero(ws):
    result = create(ws)

    assert result["stock"] == 0
    assert result["cost_price"] == Decimal("0.00")
    assert result["status"] == "ACTIVE"
    assert result["updated_by"] == ws["admin"]["id"]

    assert read(ws, result["id"]) == result


def test_duplicate_sku_is_rejected_and_original_remains(ws):
    original = create(
        ws,
        name="Phone First",
    )

    before = read(ws, original["id"])

    with pytest.raises(AppError) as caught:
        create(
            ws,
            sku=original["sku"],
            name="Phone Second",
        )

    assert caught.value.error_code == "PRODUCT_EXISTS"
    assert read(ws, original["id"]) == before

    with ws["factory"]() as session:
        count = session.execute(
            text("""
                SELECT COUNT(*)
                FROM products
                WHERE sku = :sku
            """),
            {"sku": original["sku"]},
        ).scalar_one()

    assert count == 1


def test_duplicate_variant_with_new_sku_is_rejected(ws):
    original = create(
        ws,
        name="Phone Duplicate",
    )

    with pytest.raises(AppError) as caught:
        create(
            ws,
            name="Phone Duplicate",
            storage="128GB",
            color="Black",
        )

    assert caught.value.error_code == "PRODUCT_EXISTS"
    assert read(ws, original["id"])["status"] == "ACTIVE"


def test_stock08_duplicate_rename_preserves_old_product(ws):
    first = create(ws, name="Phone One")
    create(ws, name="Phone Two")

    before = read(ws, first["id"])

    with pytest.raises(AppError) as caught:
        ws["editor"].update_details(
            **edit_values(
                ws,
                first["id"],
                name="Phone Two",
            )
        )

    assert caught.value.error_code == "PRODUCT_EXISTS"
    assert read(ws, first["id"]) == before


def test_stock09_valid_rename_preserves_inventory_and_cost(ws):
    product = create(ws, name="Phone Before")

    # Chỉ đặt số liệu mẫu trong phone_shop_test.
    ws["db"].execute(
        text("""
            UPDATE products
            SET stock = :stock,
                cost_price = :cost
            WHERE id = :id
        """),
        {
            "stock": 7,
            "cost": Decimal("9500000.00"),
            "id": product["id"],
        },
    )

    before = read(ws, product["id"])

    after = ws["editor"].update_details(
        **edit_values(
            ws,
            product["id"],
            name="Phone After",
            min_stock=4,
        )
    )

    assert after["name"] == "Phone After"
    assert after["min_stock"] == 4
    assert after["sell_price"] == Decimal("13500000.00")
    assert after["updated_by"] == ws["admin"]["id"]

    for field in (
        "id",
        "sku",
        "brand_id",
        "storage",
        "color",
        "stock",
        "cost_price",
        "status",
    ):
        assert after[field] == before[field]


@pytest.mark.parametrize(
    "price",
    ["0", "-1", "-999", "1.234"],
)
def test_create_with_invalid_price_is_rejected(ws, price):
    sku = f"T31-BAD-{token_hex(6)}"

    with pytest.raises(AppError) as caught:
        create(
            ws,
            sku=sku,
            sell_price=price,
        )

    assert caught.value.error_code == "VALIDATION_ERROR"

    with ws["factory"]() as session:
        assert ProductRepository(session).get_by_sku(sku) is None


@pytest.mark.parametrize(
    "price",
    ["0", "-1", "-999", "1.234"],
)
def test_edit_with_invalid_price_preserves_product(
    ws,
    price,
):
    product = create(ws)
    before = read(ws, product["id"])

    with pytest.raises(AppError) as caught:
        ws["editor"].update_details(
            **edit_values(
                ws,
                product["id"],
                sell_price=price,
            )
        )

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert read(ws, product["id"]) == before


@pytest.mark.parametrize(
    "column",
    [
        "sku",
        "name",
        "brand_id",
        "storage",
        "color",
        "sell_price",
        "stock",
        "min_stock",
    ],
)
def test_not_null_constraint_rejects_null(ws, column):
    """Safe whitelist: column is selected only from fixed test values."""

    product = create(ws)
    before = read(ws, product["id"])

    with (
        pytest.raises(DBAPIError),
        ws["factory"]() as session,
        session.begin(),
    ):
        session.execute(
            text(f"""
                UPDATE products
                SET {column} = NULL
                WHERE id = :product_id
            """),
            {"product_id": product["id"]},
        )

    assert read(ws, product["id"]) == before


def test_database_check_rejects_negative_sell_price(ws):
    product = create(ws)
    before = read(ws, product["id"])

    with (
        pytest.raises(DBAPIError),
        ws["factory"]() as session,
        session.begin(),
    ):
        session.execute(
            text("""
                UPDATE products
                SET sell_price = -100
                WHERE id = :product_id
            """),
            {"product_id": product["id"]},
        )

    assert read(ws, product["id"]) == before


def test_stock10_database_check_rejects_negative_stock(ws):
    product = create(ws)
    before = read(ws, product["id"])

    with (
        pytest.raises(DBAPIError),
        ws["factory"]() as session,
        session.begin(),
    ):
        session.execute(
            text("""
                UPDATE products
                SET stock = -1
                WHERE id = :product_id
            """),
            {"product_id": product["id"]},
        )

    assert read(ws, product["id"]) == before


def test_discontinue_restore_and_sale_precheck(ws):
    product = create(ws)
    before = read(ws, product["id"])

    stopped = ws["management"].set_status(
        session_store=ws["admin"]["store"],
        product_id=product["id"],
        status="DISCONTINUED",
    )

    assert stopped["status"] == "DISCONTINUED"
    assert stopped["stock"] == before["stock"]
    assert stopped["cost_price"] == before["cost_price"]

    public = ws["management"].search_public(
        keyword=product["sku"],
    )
    assert public["total"] == 0

    admin = ws["management"].search_admin(
        session_store=ws["admin"]["store"],
        keyword=product["sku"],
        status="DISCONTINUED",
    )
    assert admin["total"] == 1
    assert admin["items"][0]["id"] == product["id"]

    with (
        ws["factory"]() as session,
        session.begin(),
        pytest.raises(AppError) as caught,
    ):
        ProductManagementService.require_active_for_sale(
            repository=ProductRepository(session),
            product_id=product["id"],
        )

    assert caught.value.error_code == "PRODUCT_DISCONTINUED"

    restored = ws["management"].set_status(
        session_store=ws["admin"]["store"],
        product_id=product["id"],
        status="ACTIVE",
    )

    assert restored["status"] == "ACTIVE"
    assert ws["management"].search_public(
        keyword=product["sku"],
    )["total"] == 1


def test_public_results_never_expose_cost_or_exact_stock(ws):
    product = create(ws)

    # Số liệu mẫu để kiểm tra không lộ giá vốn.
    ws["db"].execute(
        text("""
            UPDATE products
            SET stock = 8,
                cost_price = 9000000
            WHERE id = :id
        """),
        {"id": product["id"]},
    )

    public = ws["management"].search_public(
        keyword=product["sku"],
    )

    assert public["total"] == 1

    item = public["items"][0]
    assert item["id"] == product["id"]
    assert bool(item["in_stock"]) is True

    for private_field in (
        "cost_price",
        "stock",
        "min_stock",
        "is_low_stock",
        "updated_by",
    ):
        assert private_field not in item

    admin = ws["management"].search_admin(
        session_store=ws["admin"]["store"],
        keyword=product["sku"],
    )

    assert admin["items"][0]["stock"] == 8
    assert admin["items"][0]["cost_price"] == Decimal(
        "9000000.00"
    )


def test_customer_cannot_use_admin_product_services(ws):
    product = create(ws)
    before = read(ws, product["id"])
    customer_store = ws["customer"]["store"]

    operations = [
        lambda: ws["creator"].create(
            **create_values(
                ws,
                session_store=customer_store,
            )
        ),
        lambda: ws["editor"].update_details(
            **edit_values(
                ws,
                product["id"],
                session_store=customer_store,
            )
        ),
        lambda: ws["management"].set_status(
            session_store=customer_store,
            product_id=product["id"],
            status="DISCONTINUED",
        ),
        lambda: ws["management"].search_admin(
            session_store=customer_store,
        ),
    ]

    for operation in operations:
        with pytest.raises(AppError) as caught:
            operation()

        assert caught.value.error_code == "FORBIDDEN"

    assert read(ws, product["id"]) == before


def test_low_stock_includes_equal_threshold(ws):
    equal = create(
        ws,
        name="Phone Equal",
        min_stock=3,
    )

    normal = create(
        ws,
        name="Phone Normal",
        min_stock=3,
    )

    # Dựng hai mức tồn chỉ trong transaction test.
    ws["db"].execute(
        text("""
            UPDATE products SET stock = :stock
            WHERE id = :id
        """),
        {"stock": 3, "id": equal["id"]},
    )

    ws["db"].execute(
        text("""
            UPDATE products SET stock = :stock
            WHERE id = :id
        """),
        {"stock": 4, "id": normal["id"]},
    )

    low = ws["management"].search_admin(
        session_store=ws["admin"]["store"],
        status="ACTIVE",
        low_stock=True,
    )

    ids = {row["id"] for row in low["items"]}
    assert equal["id"] in ids
    assert normal["id"] not in ids


def test_client_cannot_override_stock_or_cost(ws):
    product = create(ws)
    before = read(ws, product["id"])

    with pytest.raises(TypeError):
        ws["creator"].create(
            **create_values(ws),
            stock=100,
        )

    with pytest.raises(TypeError):
        ws["editor"].update_details(
            **edit_values(ws, product["id"]),
            cost_price=Decimal("1.00"),
        )

    assert read(ws, product["id"]) == before


def test_unauthenticated_user_cannot_create_product(ws):
    with pytest.raises(AppError) as caught:
        ws["creator"].create(
            **create_values(
                ws,
                session_store=Store(),
            )
        )

    assert caught.value.error_code == "UNAUTHORIZED"
