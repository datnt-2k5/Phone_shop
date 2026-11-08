
"""US03 Task 20 - Integration Test password va avatar.

Can migration avatar_url tren phone_shop_test.
Moi bai test duoc rollback boi fixture test_db.
"""

from datetime import UTC, datetime
from io import BytesIO
from secrets import token_hex

import bcrypt
import pytest
from PIL import Image
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from models.app_error import AppError
from services.account_security_service import (
    MAX_AVATAR_BYTES,
    AccountSecurityService,
)
from services.auth_service import AuthService
from services.auth_session import AUTH_SESSION_USER_ID_KEY
from utils.time_utils import FixedClock

OLD_PASSWORD = "MatKhau123!"
NEW_PASSWORD = "MatKhauMoi456!"
FIXED_TIME = datetime(2026, 11, 8, 10, 30)


class StrictSessionStore:
    def __init__(self):
        self.data = {}

    def set(self, key, value):
        self.data[key] = value

    def get(self, key):
        return self.data.get(key)

    def remove(self, key):
        self.data.pop(key)


def make_image(image_format: str) -> bytes:
    output = BytesIO()
    Image.new(
        "RGB",
        (32, 32),
        (100, 120, 140),
    ).save(output, format=image_format)
    return output.getvalue()


def make_session_factory(connection: Connection):
    def create_session() -> Session:
        return Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
        )

    return create_session


def read_account(connection: Connection, user_id: int):
    row = connection.execute(
        text("""
            SELECT
                id,
                email,
                password_hash,
                role,
                status,
                avatar_url,
                updated_at,
                updated_by
            FROM users
            WHERE id = :user_id
        """),
        {"user_id": user_id},
    ).mappings().one()

    return dict(row)


@pytest.fixture
def account_context(test_db: Connection, tmp_path):
    """Tao Customer va dang nhap trong phone_shop_test."""

    # Loi ro rang neu chua chay migration cho DB test.
    columns = test_db.execute(
        text("SHOW COLUMNS FROM users LIKE 'avatar_url'")
    ).all()

    if not columns:
        pytest.fail(
            "phone_shop_test chua co avatar_url. "
            "Hay ap dung migration Task 20 truoc."
        )

    factory = make_session_factory(test_db)

    auth = AuthService(session_factory=factory)

    email = f"task20_{token_hex(8)}@example.test"

    registered = auth.register(
        email=email,
        password=OLD_PASSWORD,
        confirm_password=OLD_PASSWORD,
        full_name="Nguyễn Văn Test",
        phone="0912345678",
    )

    store = StrictSessionStore()
    auth.login(
        email=email,
        password=OLD_PASSWORD,
        session_store=store,
    )

    security = AccountSecurityService(
        session_factory=factory,
        clock=FixedClock(
            datetime(2026, 11, 8, 10, 30, tzinfo=UTC)
        ),
        avatar_dir=tmp_path / "avatars",
    )

    return {
        "db": test_db,
        "auth": auth,
        "security": security,
        "registered": registered,
        "store": store,
        "email": email,
    }


def test_change_password_updates_bcrypt_and_logs_out(
    account_context,
):
    context = account_context
    registered = context["registered"]
    db = context["db"]
    store = context["store"]

    before = read_account(db, registered.user_id)

    context["security"].change_password(
        session_store=store,
        old_password=OLD_PASSWORD,
        new_password=NEW_PASSWORD,
        confirm_new_password=NEW_PASSWORD,
    )

    after = read_account(db, registered.user_id)

    assert after["password_hash"] != before["password_hash"]
    assert bcrypt.checkpw(
        NEW_PASSWORD.encode(),
        after["password_hash"].encode(),
    )
    assert after["updated_by"] == registered.user_id
    assert after["updated_at"] == FIXED_TIME

    assert after["email"] == before["email"]
    assert after["role"] == before["role"]
    assert after["status"] == before["status"]

    # Session cu bi xoa sau khi doi thanh cong.
    assert store.get(AUTH_SESSION_USER_ID_KEY) is None

    with pytest.raises(AppError) as caught:
        context["auth"].login(
            email=context["email"],
            password=OLD_PASSWORD,
            session_store=StrictSessionStore(),
        )

    assert caught.value.error_code == "INVALID_CREDENTIALS"

    # Mat khau moi phai dang nhap duoc.
    new_store = StrictSessionStore()

    result = context["auth"].login(
        email=context["email"],
        password=NEW_PASSWORD,
        session_store=new_store,
    )

    assert result.user_id == registered.user_id


def test_wrong_old_password_preserves_data_and_session(
    account_context,
):
    context = account_context
    registered = context["registered"]
    store = context["store"]
    db = context["db"]

    before = read_account(db, registered.user_id)

    with pytest.raises(AppError) as caught:
        context["security"].change_password(
            session_store=store,
            old_password="SaiMatKhau123!",
            new_password=NEW_PASSWORD,
            confirm_new_password=NEW_PASSWORD,
        )

    assert caught.value.error_code == "INVALID_OLD_PASSWORD"
    assert read_account(db, registered.user_id) == before
    assert store.get(AUTH_SESSION_USER_ID_KEY) == registered.user_id


def test_reused_password_is_rejected(account_context):
    context = account_context
    registered = context["registered"]
    db = context["db"]

    before = read_account(db, registered.user_id)

    with pytest.raises(AppError) as caught:
        context["security"].change_password(
            session_store=context["store"],
            old_password=OLD_PASSWORD,
            new_password=OLD_PASSWORD,
            confirm_new_password=OLD_PASSWORD,
        )

    assert caught.value.error_code == "PASSWORD_REUSED"
    assert read_account(db, registered.user_id) == before


@pytest.mark.parametrize(
    "new_password",
    [
        "abc123",
        "abcdefgh",
        "A1" + "é" * 36,
    ],
)
def test_invalid_new_password_keeps_old_hash(
    account_context,
    new_password,
):
    context = account_context
    registered = context["registered"]
    db = context["db"]

    before = read_account(db, registered.user_id)

    with pytest.raises(AppError):
        context["security"].change_password(
            session_store=context["store"],
            old_password=OLD_PASSWORD,
            new_password=new_password,
            confirm_new_password=new_password,
        )

    assert read_account(db, registered.user_id) == before


def test_wrong_password_confirmation_is_rejected(
    account_context,
):
    context = account_context
    registered = context["registered"]

    before = read_account(
        context["db"],
        registered.user_id,
    )

    with pytest.raises(AppError):
        context["security"].change_password(
            session_store=context["store"],
            old_password=OLD_PASSWORD,
            new_password=NEW_PASSWORD,
            confirm_new_password="KhacMatKhau123!",
        )

    assert read_account(
        context["db"],
        registered.user_id,
    ) == before


@pytest.mark.parametrize(
    ("image_format", "extension"),
    [
        ("JPEG", ".jpg"),
        ("PNG", ".png"),
    ],
)
def test_avatar_upload_persists_to_db_and_disk(
    account_context,
    image_format,
    extension,
):
    context = account_context
    registered = context["registered"]
    db = context["db"]

    before = read_account(db, registered.user_id)

    result = context["security"].upload_avatar(
        session_store=context["store"],
        image_bytes=make_image(image_format),
    )

    after = read_account(db, registered.user_id)

    assert result.user_id == registered.user_id
    assert result.avatar_url.startswith("avatars/")
    assert result.avatar_url.endswith(extension)
    assert after["avatar_url"] == result.avatar_url

    assert after["updated_by"] == registered.user_id
    assert after["updated_at"] == FIXED_TIME

    assert after["password_hash"] == before["password_hash"]
    assert after["email"] == before["email"]
    assert after["role"] == before["role"]

    filename = result.avatar_url.removeprefix("avatars/")
    saved = context["security"].avatar_dir / filename

    assert saved.is_file()

    with Image.open(saved) as image:
        assert image.format == image_format
        assert image.size == (32, 32)

    # Upload avatar khong dang xuat tai khoan.
    assert context["store"].get(
        AUTH_SESSION_USER_ID_KEY
    ) == registered.user_id


@pytest.mark.parametrize(
    "bad_bytes",
    [
        b"not-an-image",
        b"A" * (MAX_AVATAR_BYTES + 1),
        make_image("GIF"),
    ],
)
def test_invalid_avatar_does_not_modify_database(
    account_context,
    bad_bytes,
):
    context = account_context
    registered = context["registered"]
    db = context["db"]

    before = read_account(db, registered.user_id)

    with pytest.raises(AppError):
        context["security"].upload_avatar(
            session_store=context["store"],
            image_bytes=bad_bytes,
        )

    assert read_account(db, registered.user_id) == before
    assert list(context["security"].avatar_dir.glob("*")) == []


def test_avatar_upload_cannot_change_another_user(
    account_context,
):
    context = account_context
    db = context["db"]
    factory = make_session_factory(db)

    second_email = f"task20_b_{token_hex(8)}@example.test"
    second = AuthService(session_factory=factory).register(
        email=second_email,
        password=OLD_PASSWORD,
        confirm_password=OLD_PASSWORD,
        full_name="Khách hàng B",
        phone="0987654321",
    )

    second_before = read_account(db, second.user_id)

    result = context["security"].upload_avatar(
        session_store=context["store"],
        image_bytes=make_image("PNG"),
    )

    assert result.user_id == context["registered"].user_id
    assert read_account(db, second.user_id) == second_before


@pytest.mark.parametrize("action", ["password", "avatar"])
def test_locked_account_cannot_modify_security(
    account_context,
    action,
):
    context = account_context
    db = context["db"]
    registered = context["registered"]

    db.execute(
        text("""
            UPDATE users
            SET status = 'LOCKED',
                lock_reason = 'Task 20 test'
            WHERE id = :user_id
        """),
        {"user_id": registered.user_id},
    )

    before = read_account(db, registered.user_id)

    with pytest.raises(AppError) as caught:
        if action == "password":
            context["security"].change_password(
                session_store=context["store"],
                old_password=OLD_PASSWORD,
                new_password=NEW_PASSWORD,
                confirm_new_password=NEW_PASSWORD,
            )
        else:
            context["security"].upload_avatar(
                session_store=context["store"],
                image_bytes=make_image("PNG"),
            )

    assert caught.value.error_code == "ACCOUNT_LOCKED"
    assert read_account(db, registered.user_id) == before
    assert context["store"].get(AUTH_SESSION_USER_ID_KEY) is None


@pytest.mark.parametrize("action", ["password", "avatar"])
def test_guest_cannot_modify_account(
    account_context,
    action,
):
    context = account_context
    registered = context["registered"]
    db = context["db"]
    before = read_account(db, registered.user_id)

    guest_store = StrictSessionStore()

    with pytest.raises(AppError) as caught:
        if action == "password":
            context["security"].change_password(
                session_store=guest_store,
                old_password=OLD_PASSWORD,
                new_password=NEW_PASSWORD,
                confirm_new_password=NEW_PASSWORD,
            )
        else:
            context["security"].upload_avatar(
                session_store=guest_store,
                image_bytes=make_image("PNG"),
            )

    assert caught.value.error_code == "UNAUTHORIZED"
    assert read_account(db, registered.user_id) == before
