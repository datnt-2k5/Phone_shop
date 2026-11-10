
"""Task 32: product image security and transaction tests on phone_shop_test."""

from datetime import UTC, datetime
from io import BytesIO
from secrets import token_hex
from uuid import UUID

import pytest
from PIL import Image
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from models.app_error import AppError
from repositories.product_image_repository import ProductImageRepository
from repositories.product_repository import ProductRepository
from services.auth_service import AuthService
from services.auth_session import AUTH_SESSION_USER_ID_KEY
from services.product_image_service import ProductImageService
from utils.time_utils import FixedClock

NOW = datetime(2026, 11, 10, 7, 0, tzinfo=UTC)
PASSWORD = "MatKhau123!"


class Store:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value

    def remove(self, key):
        self.data.pop(key, None)


def image_bytes(fmt="JPEG"):
    output = BytesIO()

    Image.new(
        "RGB",
        (24, 24),
        (10, 20, 50),
    ).save(
        output,
        format=fmt,
    )

    return output.getvalue()


@pytest.fixture
def ws(test_db: Connection, tmp_path):
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
            VALUES (:name, :now)
        """),
        {
            "name": f"T32 Brand {token_hex(6)}",
            "now": NOW.replace(tzinfo=None),
        },
    )

    auth = AuthService(session_factory=factory)
    accounts = {}

    for role in ("admin", "customer"):
        email = (
            f"t32_{role}_{token_hex(7)}@example.test"
        )

        registered = auth.register(
            email=email,
            password=PASSWORD,
            confirm_password=PASSWORD,
            full_name=f"Task32 {role}",
            phone="0912345678",
        )

        accounts[role] = {
            "id": registered.user_id,
            "email": email,
            "store": Store(),
        }

    # Chỉ thay role trong phone_shop_test.
    test_db.execute(
        text("""
            UPDATE users
            SET role = 'ADMIN'
            WHERE id = :id
        """),
        {"id": accounts["admin"]["id"]},
    )

    for account in accounts.values():
        auth.login(
            email=account["email"],
            password=PASSWORD,
            session_store=account["store"],
        )

    with factory() as session, session.begin():
        product_id = ProductRepository(session).create(
            sku=f"T32-{token_hex(8)}",
            name=f"Phone Task32 {token_hex(8)}",
            brand_id=int(brand.lastrowid),
            storage="128GB",
            color="Black",
            sell_price=12000000,
            now_utc=NOW.replace(tzinfo=None),
            updated_by=None,
        )

    directory = tmp_path / "products"

    return {
        "db": test_db,
        "factory": factory,
        "auth": auth,
        "admin": accounts["admin"],
        "customer": accounts["customer"],
        "product_id": product_id,
        "directory": directory,
        "service": ProductImageService(
            session_factory=factory,
            auth_service=auth,
            clock=FixedClock(NOW),
            image_dir=directory,
        ),
    }


def read(ws):
    with ws["factory"]() as session:
        return ProductRepository(session).get_by_id(
            ws["product_id"]
        )


def upload(ws, *, actor="admin", content=None):
    return ws["service"].upload(
        session_store=ws[actor]["store"],
        product_id=ws["product_id"],
        image_bytes=(
            content
            if content is not None
            else image_bytes()
        ),
    )


def files(ws):
    directory = ws["directory"]
    return (
        list(directory.iterdir())
        if directory.exists()
        else []
    )


def test_admin_uploads_jpeg_and_preserves_stock_cost(ws):
    before = read(ws)

    result = upload(ws)
    after = read(ws)

    assert result.product_id == ws["product_id"]
    assert result.image_url == after["image_url"]
    assert after["updated_by"] == ws["admin"]["id"]
    assert (
        after["updated_at"]
        == NOW.replace(tzinfo=None)
    )

    assert len(files(ws)) == 1
    saved = files(ws)[0]

    assert saved.suffix == ".jpg"
    assert UUID(saved.stem).version == 4

    with Image.open(saved) as photo:
        assert photo.format == "JPEG"

    for field in (
        "sku",
        "brand_id",
        "sell_price",
        "cost_price",
        "stock",
        "min_stock",
        "status",
    ):
        assert before[field] == after[field]


def test_admin_uploads_png(ws):
    result = upload(
        ws,
        content=image_bytes("PNG"),
    )

    assert result.image_url.endswith(".png")

    with Image.open(files(ws)[0]) as photo:
        assert photo.format == "PNG"


def test_replacement_preserves_previous_file(ws):
    first = upload(ws)

    second = upload(
        ws,
        content=image_bytes("PNG"),
    )

    assert first.image_url != second.image_url
    assert len(files(ws)) == 2
    assert read(ws)["image_url"] == second.image_url


def test_customer_cannot_upload_or_touch_file(ws):
    before = read(ws)

    with pytest.raises(AppError) as caught:
        upload(ws, actor="customer")

    assert caught.value.error_code == "FORBIDDEN"
    assert files(ws) == []
    assert read(ws) == before


def test_unauthenticated_user_cannot_upload(ws):
    with pytest.raises(AppError) as caught:
        ws["service"].upload(
            session_store=Store(),
            product_id=ws["product_id"],
            image_bytes=image_bytes(),
        )

    assert caught.value.error_code == "UNAUTHORIZED"
    assert files(ws) == []


def test_locked_admin_cannot_upload(ws):
    ws["db"].execute(
        text("""
            UPDATE users
            SET status = 'LOCKED',
                lock_reason = 'Task32'
            WHERE id = :id
        """),
        {"id": ws["admin"]["id"]},
    )

    with pytest.raises(AppError) as caught:
        upload(ws)

    assert caught.value.error_code == "ACCOUNT_LOCKED"

    assert ws["admin"]["store"].get(
        AUTH_SESSION_USER_ID_KEY
    ) is None

    assert files(ws) == []


def test_demoted_admin_cannot_upload(ws):
    ws["db"].execute(
        text("""
            UPDATE users
            SET role = 'CUSTOMER'
            WHERE id = :id
        """),
        {"id": ws["admin"]["id"]},
    )

    with pytest.raises(AppError) as caught:
        upload(ws)

    assert caught.value.error_code == "FORBIDDEN"
    assert files(ws) == []


def test_nonexistent_product_does_not_write_file(ws):
    with pytest.raises(AppError) as caught:
        ws["service"].upload(
            session_store=ws["admin"]["store"],
            product_id=999999999999,
            image_bytes=image_bytes(),
        )

    assert caught.value.error_code == "NOT_FOUND"
    assert files(ws) == []


def test_invalid_content_does_not_write_file(ws):
    before = read(ws)

    with pytest.raises(AppError) as caught:
        upload(
            ws,
            content=b"not-an-image",
        )

    assert (
        caught.value.error_code
        == "INVALID_PRODUCT_IMAGE"
    )
    assert files(ws) == []
    assert read(ws) == before


def test_forced_database_error_rolls_back_and_removes_file(ws):
    class BrokenRepository(ProductImageRepository):
        def update_image_url(self, **kwargs):
            raise RuntimeError("database update failed")

    service = ProductImageService(
        session_factory=ws["factory"],
        auth_service=ws["auth"],
        image_dir=ws["directory"],
        clock=FixedClock(NOW),
        repository_factory=BrokenRepository,
    )

    before = read(ws)

    with pytest.raises(
        RuntimeError,
        match="database update failed",
    ):
        service.upload(
            session_store=ws["admin"]["store"],
            product_id=ws["product_id"],
            image_bytes=image_bytes(),
        )

    assert files(ws) == []
    assert read(ws) == before
