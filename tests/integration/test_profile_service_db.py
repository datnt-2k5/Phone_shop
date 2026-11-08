
"""US03 Task 17: Integration Test hồ sơ với MariaDB.

Chỉ sử dụng phone_shop_test thông qua fixture test_db.
Không thay đổi dữ liệu trong phone_shop.
"""

from dataclasses import asdict
from datetime import UTC, datetime
from secrets import token_hex

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from models.app_error import AppError
from services.auth_service import AuthService
from services.auth_session import AUTH_SESSION_USER_ID_KEY
from services.profile_service import ProfileService
from utils.time_utils import FixedClock

PASSWORD = "MatKhau123!"
FIXED_TIME = datetime(2026, 11, 8, 7, 15)


class StrictSessionStore:
    """Mô phỏng Flet Session Store."""

    def __init__(self):
        self.data = {}

    def set(self, key, value):
        self.data[key] = value

    def get(self, key):
        return self.data.get(key)

    def remove(self, key):
        self.data.pop(key)


def _email():
    """Tạo email khác nhau cho mỗi tài khoản kiểm thử."""

    return f"task17_{token_hex(6)}@example.test"


def _session_factory(connection: Connection):
    """Tạo Session an toàn trên phone_shop_test."""

    def make_session() -> Session:
        return Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
        )

    return make_session


def _register(auth: AuthService):
    """Tạo tài khoản mới bằng nghiệp vụ đăng ký thật."""

    return auth.register(
        email=_email(),
        password=PASSWORD,
        confirm_password=PASSWORD,
        full_name="Nguyễn Văn A",
        phone="0912345678",
    )


def _read_user(
    connection: Connection,
    user_id: int,
):
    """Đọc trực tiếp bản ghi để kiểm tra dữ liệu MariaDB."""

    row = connection.execute(
        text("""
            SELECT
                id,
                email,
                password_hash,
                full_name,
                phone,
                address,
                role,
                status,
                created_at,
                updated_at,
                updated_by
            FROM users
            WHERE id = :user_id
        """),
        {"user_id": user_id},
    ).mappings().one()

    return dict(row)


@pytest.fixture
def profile_context(test_db: Connection):
    """Tạo Customer, đăng nhập, cung cấp ProfileService."""

    factory = _session_factory(test_db)

    auth = AuthService(session_factory=factory)
    registered = _register(auth)

    store = StrictSessionStore()

    auth.login(
        email=registered.email,
        password=PASSWORD,
        session_store=store,
    )

    profile = ProfileService(
        session_factory=factory,
        clock=FixedClock(
            datetime(2026, 11, 8, 7, 15, tzinfo=UTC)
        ),
    )

    return test_db, auth, registered, store, profile


def test_get_my_profile_reads_real_database(
    profile_context,
):
    """Đọc hồ sơ đã xác thực, không trả mật khẩu."""

    _, _, registered, store, profile = profile_context

    result = profile.get_my_profile(
        session_store=store,
    )

    assert result.user_id == registered.user_id
    assert result.email == registered.email
    assert result.full_name == "Nguyễn Văn A"
    assert result.phone == "0912345678"
    assert result.address is None
    assert result.role == "CUSTOMER"
    assert result.status == "ACTIVE"

    data = asdict(result)

    assert "password" not in data
    assert "password_hash" not in data


def test_update_profile_persists_and_sets_audit(
    profile_context,
):
    """Lưu hồ sơ thật và cập nhật updated_at/updated_by."""

    connection, _, registered, store, profile = profile_context

    before = _read_user(connection, registered.user_id)

    result = profile.update_my_profile(
        session_store=store,
        full_name="  Nguyễn   Văn   Mới  ",
        phone="  0901234567  ",
        address="  Thành phố Đà Nẵng  ",
    )

    after = _read_user(connection, registered.user_id)

    assert result.full_name == "Nguyễn Văn Mới"
    assert result.phone == "0901234567"
    assert result.address == "Thành phố Đà Nẵng"

    assert after["full_name"] == result.full_name
    assert after["phone"] == result.phone
    assert after["address"] == result.address

    assert after["updated_at"] == FIXED_TIME
    assert after["updated_by"] == registered.user_id

    # Những dữ liệu không được phép sửa phải giữ nguyên.
    for field in (
        "email",
        "password_hash",
        "role",
        "status",
        "created_at",
    ):
        assert after[field] == before[field]


def test_address_can_be_cleared(
    profile_context,
):
    """Địa chỉ trống được lưu thành NULL."""

    connection, _, registered, store, profile = profile_context

    profile.update_my_profile(
        session_store=store,
        full_name="Nguyễn Văn A",
        phone="0912345678",
        address="Hà Nội",
    )

    updated = profile.update_my_profile(
        session_store=store,
        full_name="Nguyễn Văn A",
        phone="0912345678",
        address="   ",
    )

    assert updated.address is None

    row = _read_user(connection, registered.user_id)
    assert row["address"] is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("full_name", "   "),
        ("phone", "123456"),
        ("address", "A" * 256),
    ],
)
def test_invalid_data_does_not_modify_database(
    profile_context,
    field,
    value,
):
    """Dữ liệu sai không được ghi hoặc cập nhật audit."""

    connection, _, registered, store, profile = profile_context
    before = _read_user(connection, registered.user_id)

    values = {
        "full_name": "Nguyễn Văn A",
        "phone": "0912345678",
        "address": "Đà Nẵng",
    }
    values[field] = value

    with pytest.raises(AppError) as caught:
        profile.update_my_profile(
            session_store=store,
            **values,
        )

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert field in caught.value.errors

    after = _read_user(connection, registered.user_id)
    assert after == before


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("email", "hacker@example.test"),
        ("role", "SUPER_ADMIN"),
        ("status", "ACTIVE"),
        ("user_id", 999999),
        ("updated_by", 999999),
    ],
)
def test_forged_parameters_are_rejected(
    profile_context,
    field,
    value,
):
    """Không cho client gửi trường ngoài danh sách được sửa."""

    connection, _, registered, store, profile = profile_context
    before = _read_user(connection, registered.user_id)

    values = {
        "full_name": "Nguyễn Văn A",
        "phone": "0912345678",
        "address": "Đà Nẵng",
        field: value,
    }

    with pytest.raises(TypeError):
        profile.update_my_profile(
            session_store=store,
            **values,
        )

    after = _read_user(connection, registered.user_id)
    assert after == before


@pytest.mark.parametrize(
    "action",
    ["read", "update"],
)
def test_guest_cannot_read_or_update_profile(
    profile_context,
    action,
):
    """Không có session thì không có quyền xem hay sửa."""

    connection, _, registered, _, profile = profile_context
    guest_store = StrictSessionStore()
    before = _read_user(connection, registered.user_id)

    with pytest.raises(AppError) as caught:
        if action == "read":
            profile.get_my_profile(
                session_store=guest_store,
            )
        else:
            profile.update_my_profile(
                session_store=guest_store,
                full_name="Tên mới",
                phone="0901234567",
                address=None,
            )

    assert caught.value.error_code == "UNAUTHORIZED"
    assert _read_user(connection, registered.user_id) == before


def test_update_only_changes_own_account(
    profile_context,
):
    """Cập nhật của Customer A không ảnh hưởng Customer B."""

    connection, auth, first, store, profile = profile_context
    second = _register(auth)

    before_second = _read_user(
        connection,
        second.user_id,
    )

    result = profile.update_my_profile(
        session_store=store,
        full_name="Khách hàng thứ nhất",
        phone="0901234567",
        address="Đà Nẵng",
    )

    assert result.user_id == first.user_id

    after_second = _read_user(
        connection,
        second.user_id,
    )

    assert after_second == before_second


@pytest.mark.parametrize(
    "action",
    ["read", "update"],
)
def test_locked_account_cannot_use_profile(
    profile_context,
    action,
):
    """Khóa tài khoản sau login phải chặn xem và sửa."""

    connection, _, registered, store, profile = profile_context

    connection.execute(
        text("""
            UPDATE users
            SET
                status = 'LOCKED',
                lock_reason = 'Task 17 test'
            WHERE id = :user_id
        """),
        {"user_id": registered.user_id},
    )

    with pytest.raises(AppError) as caught:
        if action == "read":
            profile.get_my_profile(session_store=store)
        else:
            profile.update_my_profile(
                session_store=store,
                full_name="Tên mới",
                phone="0901234567",
                address=None,
            )

    assert caught.value.error_code == "ACCOUNT_LOCKED"
    assert store.get(AUTH_SESSION_USER_ID_KEY) is None


def test_admin_can_update_only_own_profile(
    profile_context,
):
    """Admin được sửa hồ sơ của chính mình, không đổi role."""

    connection, _, registered, store, profile = profile_context

    # Chỉ thay role trong database kiểm thử.
    connection.execute(
        text("""
            UPDATE users
            SET role = 'ADMIN'
            WHERE id = :user_id
        """),
        {"user_id": registered.user_id},
    )

    result = profile.update_my_profile(
        session_store=store,
        full_name="Admin Test",
        phone="0901234567",
        address="Đà Nẵng",
    )

    assert result.user_id == registered.user_id
    assert result.role == "ADMIN"
    assert result.updated_by == registered.user_id

    row = _read_user(connection, registered.user_id)
    assert row["role"] == "ADMIN"
    assert row["full_name"] == "Admin Test"
