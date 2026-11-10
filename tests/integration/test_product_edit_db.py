
"""Task 28: kiểm thử sửa sản phẩm trên phone_shop_test."""

from datetime import UTC, datetime
from decimal import Decimal
from secrets import token_hex

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from models.app_error import AppError
from repositories.product_repository import ProductRepository
from services.auth_service import AuthService
from services.auth_session import AUTH_SESSION_USER_ID_KEY
from services.product_edit_service import ProductEditService
from utils.time_utils import FixedClock

CREATE_TIME = datetime(2026, 11, 10, 1, 0)
UPDATE_TIME = datetime(2026, 11, 10, 3, 0, tzinfo=UTC)
PASSWORD = "MatKhau123!"


class TestSessionStore:
    __test__ = False

    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value

    def remove(self, key):
        self.data.pop(key, None)


@pytest.fixture
def workspace(test_db: Connection):
    """Tạo dữ liệu chỉ trong transaction kiểm thử."""

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
            "name": f"T28 Brand {token_hex(6)}",
            "created_at": CREATE_TIME,
        },
    )

    brand_id = int(brand.lastrowid)

    auth = AuthService(session_factory=factory)

    users = {}

    for key in ("admin", "customer"):
        email = f"t28_{key}_{token_hex(8)}@example.test"

        registered = auth.register(
            email=email,
            password=PASSWORD,
            confirm_password=PASSWORD,
            full_name=f"Task28 {key}",
            phone="0912345678",
        )

        users[key] = {
            "id": registered.user_id,
            "email": email,
            "store": TestSessionStore(),
        }

    # Chỉ đổi role tài khoản vừa tạo trong phone_shop_test.
    test_db.execute(
        text("""
            UPDATE users
            SET role = 'ADMIN'
            WHERE id = :id
        """),
        {"id": users["admin"]["id"]},
    )

    for account in users.values():
        auth.login(
            email=account["email"],
            password=PASSWORD,
            session_store=account["store"],
        )

    service = ProductEditService(
        session_factory=factory,
        auth_service=auth,
        clock=FixedClock(UPDATE_TIME),
    )

    return {
        "db": test_db,
        "factory": factory,
        "brand_id": brand_id,
        "auth": auth,
        "service": service,
        "admin": users["admin"],
        "customer": users["customer"],
    }


def create_product(ws, *, name=None):
    token = token_hex(6)

    with ws["factory"]() as session, session.begin():
        return ProductRepository(session).create(
            sku=f"T28-{token}",
            name=name or f"Phone {token}",
            brand_id=ws["brand_id"],
            storage="128GB",
            color="Black",
            sell_price=Decimal("12000000.00"),
            description="Mô tả cũ",
            image_url="/images/old.png",
            min_stock=2,
            now_utc=CREATE_TIME,
            updated_by=None,
        )


def read_product(ws, product_id):
    with ws["factory"]() as session:
        return ProductRepository(session).get_by_id(product_id)


def edit_params(ws, product_id, *, actor="admin", **changes):
    return {
        "session_store": ws[actor]["store"],
        "product_id": product_id,
        "name": "Phone Premium",
        "description": "Mô tả được cập nhật",
        "sell_price": Decimal("13500000.50"),
        "image_url": "/images/new.png",
        "min_stock": 5,
    } | changes


def test_admin_updates_allowed_fields_and_preserves_inventory(
    workspace,
):
    ws = workspace
    product_id = create_product(ws)
    before = read_product(ws, product_id)

    after = ws["service"].update_details(
        **edit_params(ws, product_id)
    )

    assert after["name"] == "Phone Premium"
    assert after["description"] == "Mô tả được cập nhật"
    assert after["sell_price"] == Decimal("13500000.50")
    assert after["image_url"] == "/images/new.png"
    assert after["min_stock"] == 5
    assert after["updated_by"] == ws["admin"]["id"]
    assert after["updated_at"] == UPDATE_TIME.replace(tzinfo=None)

    for field in (
        "sku",
        "brand_id",
        "storage",
        "color",
        "stock",
        "cost_price",
        "status",
    ):
        assert after[field] == before[field]

    assert read_product(ws, product_id) == after


def test_customer_is_forbidden_and_cannot_change_data(workspace):
    ws = workspace
    product_id = create_product(ws)
    before = read_product(ws, product_id)

    with pytest.raises(AppError) as caught:
        ws["service"].update_details(
            **edit_params(
                ws,
                product_id,
                actor="customer",
            )
        )

    assert caught.value.error_code == "FORBIDDEN"
    assert read_product(ws, product_id) == before


def test_super_admin_can_update_product(workspace):
    ws = workspace
    product_id = create_product(ws)

    ws["db"].execute(
        text("""
            UPDATE users SET role = 'SUPER_ADMIN'
            WHERE id = :id
        """),
        {"id": ws["customer"]["id"]},
    )

    result = ws["service"].update_details(
        **edit_params(
            ws,
            product_id,
            actor="customer",
        )
    )

    assert result["updated_by"] == ws["customer"]["id"]
    assert result["name"] == "Phone Premium"


def test_locked_admin_cannot_update_and_session_is_cleared(
    workspace,
):
    ws = workspace
    product_id = create_product(ws)
    before = read_product(ws, product_id)

    ws["db"].execute(
        text("""
            UPDATE users
            SET status = 'LOCKED',
                lock_reason = 'Task 28 test'
            WHERE id = :id
        """),
        {"id": ws["admin"]["id"]},
    )

    with pytest.raises(AppError) as caught:
        ws["service"].update_details(
            **edit_params(ws, product_id)
        )

    assert caught.value.error_code == "ACCOUNT_LOCKED"
    assert ws["admin"]["store"].get(
        AUTH_SESSION_USER_ID_KEY
    ) is None
    assert read_product(ws, product_id) == before


def test_role_demotion_revokes_edit_permission(workspace):
    ws = workspace
    product_id = create_product(ws)
    before = read_product(ws, product_id)

    ws["db"].execute(
        text("""
            UPDATE users SET role = 'CUSTOMER'
            WHERE id = :id
        """),
        {"id": ws["admin"]["id"]},
    )

    with pytest.raises(AppError) as caught:
        ws["service"].update_details(
            **edit_params(ws, product_id)
        )

    assert caught.value.error_code == "FORBIDDEN"
    assert read_product(ws, product_id) == before


def test_promotion_grants_edit_permission(workspace):
    ws = workspace
    product_id = create_product(ws)

    ws["db"].execute(
        text("""
            UPDATE users SET role = 'ADMIN'
            WHERE id = :id
        """),
        {"id": ws["customer"]["id"]},
    )

    result = ws["service"].update_details(
        **edit_params(
            ws,
            product_id,
            actor="customer",
        )
    )

    assert result["name"] == "Phone Premium"


def test_duplicate_name_is_rejected_without_changing_product(
    workspace,
):
    ws = workspace
    first = create_product(ws, name="Phone One")
    create_product(ws, name="Phone Two")
    before = read_product(ws, first)

    with pytest.raises(AppError) as caught:
        ws["service"].update_details(
            **edit_params(
                ws,
                first,
                name="Phone Two",
            )
        )

    assert caught.value.error_code == "PRODUCT_EXISTS"
    assert read_product(ws, first) == before


def test_rename_to_own_name_is_allowed(workspace):
    ws = workspace
    product_id = create_product(ws, name="Phone One")

    result = ws["service"].update_details(
        **edit_params(
            ws,
            product_id,
            name="Phone One",
        )
    )

    assert result["name"] == "Phone One"


@pytest.mark.parametrize(
    "price",
    ["0", "-1", "NaN", "1.234", True, 1.5],
)
def test_invalid_price_does_not_change_product(
    workspace,
    price,
):
    ws = workspace
    product_id = create_product(ws)
    before = read_product(ws, product_id)

    with pytest.raises(AppError) as caught:
        ws["service"].update_details(
            **edit_params(
                ws,
                product_id,
                sell_price=price,
            )
        )

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert read_product(ws, product_id) == before


@pytest.mark.parametrize(
    "min_stock",
    [-1, True, "5"],
)
def test_invalid_min_stock_does_not_change_product(
    workspace,
    min_stock,
):
    ws = workspace
    product_id = create_product(ws)
    before = read_product(ws, product_id)

    with pytest.raises(AppError) as caught:
        ws["service"].update_details(
            **edit_params(
                ws,
                product_id,
                min_stock=min_stock,
            )
        )

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert read_product(ws, product_id) == before


def test_invalid_image_url_is_rejected(workspace):
    ws = workspace
    product_id = create_product(ws)
    before = read_product(ws, product_id)

    with pytest.raises(AppError) as caught:
        ws["service"].update_details(
            **edit_params(
                ws,
                product_id,
                image_url="javascript:alert(1)",
            )
        )

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert read_product(ws, product_id) == before


def test_description_and_image_can_be_cleared(workspace):
    ws = workspace
    product_id = create_product(ws)

    result = ws["service"].update_details(
        **edit_params(
            ws,
            product_id,
            description="",
            image_url="",
        )
    )

    assert result["description"] is None
    assert result["image_url"] is None


def test_stock_and_cost_cannot_be_supplied_to_service(workspace):
    ws = workspace
    product_id = create_product(ws)
    before = read_product(ws, product_id)

    with pytest.raises(TypeError):
        ws["service"].update_details(
            **edit_params(ws, product_id),
            stock=100,
        )

    with pytest.raises(TypeError):
        ws["service"].update_details(
            **edit_params(ws, product_id),
            cost_price=Decimal("1.00"),
        )

    assert read_product(ws, product_id) == before


def test_missing_product_returns_not_found(workspace):
    ws = workspace

    with pytest.raises(AppError) as caught:
        ws["service"].update_details(
            **edit_params(ws, 999999999999)
        )

    assert caught.value.error_code == "NOT_FOUND"
