
"""US03 Task 19 - Integration Test quyền OWN trên MariaDB.

Chỉ sử dụng database phone_shop_test qua fixture test_db.
Mỗi bài test dùng transaction và được rollback khi kết thúc.
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
FIXED_TIME = datetime(2026, 11, 8, 9, 30)


class StrictSessionStore:
    """Session giả lập có hành vi remove giống Flet."""

    def __init__(self) -> None:
        self.data: dict[str, object] = {}

    def set(self, key: str, value: object) -> None:
        self.data[key] = value

    def get(self, key: str) -> object | None:
        return self.data.get(key)

    def remove(self, key: str) -> None:
        self.data.pop(key)


def _unique_email() -> str:
    """Email duy nhất để các lần chạy test không trùng nhau."""

    return f"task19_{token_hex(8)}@example.test"


def _session_factory(connection: Connection):
    """SQLAlchemy Session gắn với transaction kiểm thử."""

    def create_session() -> Session:
        return Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
        )

    return create_session


def _read_user(
    connection: Connection,
    user_id: int,
) -> dict:
    """Đọc trực tiếp bản ghi users để so sánh trước/sau."""

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


def _register(auth: AuthService, full_name: str):
    """Đăng ký Customer mới qua AuthService thật."""

    return auth.register(
        email=_unique_email(),
        password=PASSWORD,
        confirm_password=PASSWORD,
        full_name=full_name,
        phone="0912345678",
    )


@pytest.fixture
def two_users(test_db: Connection):
    """Hai Customer thật, hai Session, một ProfileService."""

    factory = _session_factory(test_db)

    auth = AuthService(
        session_factory=factory,
    )

    customer_a = _register(
        auth,
        "Khách hàng A",
    )
    customer_b = _register(
        auth,
        "Khách hàng B",
    )

    session_a = StrictSessionStore()
    session_b = StrictSessionStore()

    # Đăng nhập riêng từng tài khoản.
    auth.login(
        email=customer_a.email,
        password=PASSWORD,
        session_store=session_a,
    )
    auth.login(
        email=customer_b.email,
        password=PASSWORD,
        session_store=session_b,
    )

    profile_service = ProfileService(
        session_factory=factory,
        clock=FixedClock(
            datetime(2026, 11, 8, 9, 30, tzinfo=UTC)
        ),
    )

    return {
        "db": test_db,
        "auth": auth,
        "profile": profile_service,
        "a": customer_a,
        "b": customer_b,
        "session_a": session_a,
        "session_b": session_b,
    }


def _update(
    context: dict,
    session_store: StrictSessionStore,
    *,
    full_name: str = "Tên mới",
    phone: str = "0901234567",
    address: str | None = "Đà Nẵng",
):
    """Gọi Service cập nhật với đúng 3 trường được phép."""

    return context["profile"].update_my_profile(
        session_store=session_store,
        full_name=full_name,
        phone=phone,
        address=address,
    )


def test_customer_a_updates_only_own_profile(two_users) -> None:
    """A sửa hồ sơ A, không được làm thay đổi B."""

    context = two_users
    db = context["db"]
    a = context["a"]
    b = context["b"]

    before_a = _read_user(db, a.user_id)
    before_b = _read_user(db, b.user_id)

    result = _update(
        context,
        context["session_a"],
        full_name="  Nguyễn   Văn   A Mới  ",
        phone=" 0901234567 ",
        address="  Đà Nẵng  ",
    )

    after_a = _read_user(db, a.user_id)
    after_b = _read_user(db, b.user_id)

    assert result.user_id == a.user_id
    assert result.full_name == "Nguyễn Văn A Mới"
    assert result.phone == "0901234567"
    assert result.address == "Đà Nẵng"

    assert after_a["full_name"] == "Nguyễn Văn A Mới"
    assert after_a["phone"] == "0901234567"
    assert after_a["address"] == "Đà Nẵng"

    # Audit phải do server ghi theo danh tính thật.
    assert after_a["updated_by"] == a.user_id
    assert after_a["updated_at"] == FIXED_TIME

    # Những cột bị bảo vệ của A phải giữ nguyên.
    for field in (
        "id",
        "email",
        "password_hash",
        "role",
        "status",
        "created_at",
    ):
        assert after_a[field] == before_a[field]

    # Toàn bộ hồ sơ B, kể cả audit, phải giữ nguyên.
    assert after_b == before_b


def test_customer_b_updates_only_own_profile(two_users) -> None:
    """B sửa hồ sơ B, không được thay đổi A."""

    context = two_users
    db = context["db"]
    a = context["a"]
    b = context["b"]

    before_a = _read_user(db, a.user_id)

    result = _update(
        context,
        context["session_b"],
        full_name="Khách hàng B mới",
        phone="0987654321",
        address="Hà Nội",
    )

    after_a = _read_user(db, a.user_id)
    after_b = _read_user(db, b.user_id)

    assert result.user_id == b.user_id
    assert after_b["full_name"] == "Khách hàng B mới"
    assert after_b["updated_by"] == b.user_id
    assert after_b["updated_at"] == FIXED_TIME

    # Việc B cập nhật không ảnh hưởng A.
    assert after_a == before_a


@pytest.mark.parametrize(
    ("forged_field", "forged_value"),
    [
        ("user_id", 999999),
        ("id", 999999),
        ("email", "attacker@example.test"),
        ("role", "SUPER_ADMIN"),
        ("status", "ACTIVE"),
        ("password_hash", "FAKE_HASH"),
        ("updated_at", datetime(2030, 1, 1)),
        ("updated_by", 999999),
    ],
)
def test_forged_parameters_cannot_modify_database(
    two_users,
    forged_field: str,
    forged_value: object,
) -> None:
    """Trường giả mạo bị từ chối, cả hai bản ghi không đổi."""

    context = two_users
    db = context["db"]
    a = context["a"]
    b = context["b"]

    before_a = _read_user(db, a.user_id)
    before_b = _read_user(db, b.user_id)

    payload = {
        "full_name": "Tên đã bị sửa trái phép",
        "phone": "0901234567",
        "address": "Địa chỉ giả",
        forged_field: forged_value,
    }

    with pytest.raises(TypeError):
        context["profile"].update_my_profile(
            session_store=context["session_a"],
            **payload,
        )

    assert _read_user(db, a.user_id) == before_a
    assert _read_user(db, b.user_id) == before_b


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("full_name", "   "),
        ("full_name", "A" * 101),
        ("phone", "1234567890"),
        ("phone", "0" + "\u0661" * 9),
        ("address", "X" * 256),
        ("address", 123),
    ],
)
def test_invalid_input_does_not_change_any_user(
    two_users,
    field: str,
    invalid_value: object,
) -> None:
    """Validation thất bại không làm thay đổi data hoặc audit."""

    context = two_users
    db = context["db"]
    a = context["a"]
    b = context["b"]

    before_a = _read_user(db, a.user_id)
    before_b = _read_user(db, b.user_id)

    values = {
        "full_name": "Nguyễn Văn A",
        "phone": "0912345678",
        "address": "Đà Nẵng",
    }
    values[field] = invalid_value

    with pytest.raises(AppError) as caught:
        context["profile"].update_my_profile(
            session_store=context["session_a"],
            **values,
        )

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert field in caught.value.errors

    assert _read_user(db, a.user_id) == before_a
    assert _read_user(db, b.user_id) == before_b


@pytest.mark.parametrize(
    "action",
    ["read", "update"],
)
def test_guest_cannot_access_profile(
    two_users,
    action: str,
) -> None:
    """Khách chưa đăng nhập không thể xem hoặc sửa hồ sơ."""

    context = two_users
    db = context["db"]
    a = context["a"]
    b = context["b"]

    before_a = _read_user(db, a.user_id)
    before_b = _read_user(db, b.user_id)

    guest_session = StrictSessionStore()

    with pytest.raises(AppError) as caught:
        if action == "read":
            context["profile"].get_my_profile(
                session_store=guest_session,
            )
        else:
            _update(
                context,
                guest_session,
            )

    assert caught.value.error_code == "UNAUTHORIZED"
    assert _read_user(db, a.user_id) == before_a
    assert _read_user(db, b.user_id) == before_b


@pytest.mark.parametrize(
    "action",
    ["read", "update"],
)
def test_locked_account_cannot_access_profile(
    two_users,
    action: str,
) -> None:
    """Tài khoản khóa sau login không được xem hoặc sửa."""

    context = two_users
    db = context["db"]
    a = context["a"]
    b = context["b"]
    session_a = context["session_a"]

    # Chỉ khóa tài khoản trong database kiểm thử.
    db.execute(
        text("""
            UPDATE users
            SET
                status = 'LOCKED',
                lock_reason = 'Task 19 integration test'
            WHERE id = :user_id
        """),
        {"user_id": a.user_id},
    )

    before_a = _read_user(db, a.user_id)
    before_b = _read_user(db, b.user_id)

    with pytest.raises(AppError) as caught:
        if action == "read":
            context["profile"].get_my_profile(
                session_store=session_a,
            )
        else:
            _update(
                context,
                session_a,
            )

    assert caught.value.error_code == "ACCOUNT_LOCKED"

    # Server phải xóa danh tính xác thực của tài khoản bị khóa.
    assert session_a.get(AUTH_SESSION_USER_ID_KEY) is None

    # Không có UPDATE hồ sơ trái phép.
    assert _read_user(db, a.user_id) == before_a
    assert _read_user(db, b.user_id) == before_b


def test_invalid_session_id_is_rejected(two_users) -> None:
    """Session chứa ID sai kiểu không được phép sửa dữ liệu."""

    context = two_users
    db = context["db"]
    a = context["a"]
    b = context["b"]

    before_a = _read_user(db, a.user_id)
    before_b = _read_user(db, b.user_id)

    bad_session = StrictSessionStore()
    bad_session.set(AUTH_SESSION_USER_ID_KEY, "not-an-id")

    with pytest.raises(AppError) as caught:
        _update(
            context,
            bad_session,
        )

    assert caught.value.error_code == "UNAUTHORIZED"
    assert bad_session.get(AUTH_SESSION_USER_ID_KEY) is None

    assert _read_user(db, a.user_id) == before_a
    assert _read_user(db, b.user_id) == before_b


def test_profile_result_excludes_password_hash(two_users) -> None:
    """Phản hồi Service không làm lộ dữ liệu mật khẩu."""

    context = two_users

    result = context["profile"].get_my_profile(
        session_store=context["session_a"],
    )

    data = asdict(result)

    assert "password" not in data
    assert "password_hash" not in data
    assert data["user_id"] == context["a"].user_id


def test_admin_can_only_update_own_profile(two_users) -> None:
    """ADMIN cũng chỉ sửa hồ sơ của mình qua API tự cập nhật."""

    context = two_users
    db = context["db"]
    a = context["a"]
    b = context["b"]

    # Mô phỏng cấp quyền trong database test.
    db.execute(
        text("""
            UPDATE users
            SET role = 'ADMIN'
            WHERE id = :user_id
        """),
        {"user_id": a.user_id},
    )

    before_b = _read_user(db, b.user_id)

    result = _update(
        context,
        context["session_a"],
        full_name="Admin A",
        phone="0901234567",
        address="Đà Nẵng",
    )

    after_a = _read_user(db, a.user_id)

    assert result.user_id == a.user_id
    assert result.role == "ADMIN"
    assert after_a["role"] == "ADMIN"
    assert after_a["status"] == "ACTIVE"
    assert after_a["updated_by"] == a.user_id

    # Dù là ADMIN, thao tác tự sửa vẫn không được tác động B.
    assert _read_user(db, b.user_id) == before_b
