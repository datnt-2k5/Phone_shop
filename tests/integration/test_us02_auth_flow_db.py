
"""Task 16: kiểm thử luồng US02 trên MariaDB thật.

Chỉ sử dụng fixture test_db đã cô lập phone_shop_test.
"""

from secrets import token_hex

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from models.app_error import AppError
from services.auth_service import AuthService
from services.auth_session import (
    AUTH_SESSION_USER_ID_KEY,
    CART_SESSION_KEY,
    CHECKOUT_SESSION_KEY,
    USER_CACHE_SESSION_KEY,
)

PASSWORD = "MatKhau123!"


class StrictSessionStore:
    """Giả lập đúng hành vi Flet khi remove khóa chưa tồn tại."""

    def __init__(self) -> None:
        self.data: dict[str, object] = {}

    def set(self, key: str, value: object) -> None:
        self.data[key] = value

    def get(self, key: str) -> object | None:
        return self.data.get(key)

    def remove(self, key: str) -> None:
        self.data.pop(key)


def _email() -> str:
    return f"task16_{token_hex(6)}@example.test"


def _service(test_db: Connection) -> AuthService:
    """Chỉ kết nối phone_shop_test, dùng savepoint riêng."""

    def make_session() -> Session:
        return Session(
            bind=test_db,
            join_transaction_mode="create_savepoint",
        )

    return AuthService(session_factory=make_session)


def _register(service: AuthService, email: str):
    """Tạo một Customer thật trong DB kiểm thử."""

    return service.register(
        email=email,
        password=PASSWORD,
        confirm_password=PASSWORD,
        full_name="Nguyễn Văn A",
        phone="0912345678",
    )


def _lock(test_db: Connection, user_id: int) -> None:
    """Mô phỏng admin khóa tài khoản trên DB kiểm thử."""

    test_db.execute(
        text("""
            UPDATE users
            SET status = 'LOCKED',
                lock_reason = 'Task 16 test'
            WHERE id = :user_id
        """),
        {"user_id": user_id},
    )


def test_login_logout_full_cycle_on_database(
    test_db: Connection,
) -> None:
    """ACTIVE → login → require_user → logout → UNAUTHORIZED."""

    service = _service(test_db)
    registered = _register(service, _email())
    store = StrictSessionStore()

    result = service.login(
        email=f"  {registered.email.upper()}  ",
        password=PASSWORD,
        session_store=store,
    )

    assert result.user_id == registered.user_id
    assert result.role == "CUSTOMER"
    assert store.data == {
        AUTH_SESSION_USER_ID_KEY: registered.user_id
    }

    user = service.require_user(
        session_store=store,
        allowed_roles={"CUSTOMER"},
    )
    assert user.status == "ACTIVE"
    assert user.user_id == registered.user_id

    store.set(CART_SESSION_KEY, [{"product_id": 1}])
    store.set(CHECKOUT_SESSION_KEY, "checkout-task16")
    store.set(USER_CACHE_SESSION_KEY, {"role": "CUSTOMER"})
    store.set("phone_shop.ui.theme", "dark")

    service.logout(session_store=store)
    assert store.data == {"phone_shop.ui.theme": "dark"}

    with pytest.raises(AppError) as caught:
        service.require_user(session_store=store)
    assert caught.value.error_code == "UNAUTHORIZED"

    # Logout không xóa tài khoản hay đổi trạng thái trong DB.
    status = test_db.execute(
        text("SELECT status FROM users WHERE id = :id"),
        {"id": registered.user_id},
    ).scalar_one()
    assert status == "ACTIVE"


@pytest.mark.parametrize(
    "case",
    [
        "wrong_password",
        "unknown_email",
        "invalid_email",
        "empty_email",
        "empty_password",
        "overlong_password",
    ],
)
def test_invalid_login_does_not_set_session(
    test_db: Connection,
    case: str,
) -> None:
    """Mọi lỗi thông tin đăng nhập trả một mã lỗi chung."""

    service = _service(test_db)
    registered = _register(service, _email())
    email = registered.email
    password = PASSWORD

    if case == "wrong_password":
        password = "SaiMatKhau123!"
    elif case == "unknown_email":
        email = _email()
    elif case == "invalid_email":
        email = "khong-hop-le"
    elif case == "empty_email":
        email = ""
    elif case == "empty_password":
        password = ""
    elif case == "overlong_password":
        password = "A1" + "é" * 36

    store = StrictSessionStore()
    with pytest.raises(AppError) as caught:
        service.login(
            email=email,
            password=password,
            session_store=store,
        )

    assert caught.value.error_code == "INVALID_CREDENTIALS"
    assert caught.value.message == "Email hoặc mật khẩu không đúng."
    assert store.data == {}


@pytest.mark.parametrize(
    ("password", "error_code"),
    [
        (PASSWORD, "ACCOUNT_LOCKED"),
        ("SaiMatKhau123!", "INVALID_CREDENTIALS"),
    ],
)
def test_locked_user_never_creates_session(
    test_db: Connection,
    password: str,
    error_code: str,
) -> None:
    """LOCKED không được xác thực; mật khẩu sai không lộ trạng thái."""

    service = _service(test_db)
    registered = _register(service, _email())
    _lock(test_db, registered.user_id)
    store = StrictSessionStore()

    with pytest.raises(AppError) as caught:
        service.login(
            email=registered.email,
            password=password,
            session_store=store,
        )

    assert caught.value.error_code == error_code
    assert store.data == {}


@pytest.mark.parametrize(
    "invalid_user_id",
    [None, "42", 0, -1, True, 42.0],
)
def test_invalid_session_is_rejected(
    test_db: Connection,
    invalid_user_id: object,
) -> None:
    """Session không hợp lệ không thể truy cập nghiệp vụ bảo vệ."""

    service = _service(test_db)
    store = StrictSessionStore()
    store.set(CART_SESSION_KEY, [{"product_id": 7}])

    if invalid_user_id is not None:
        store.set(AUTH_SESSION_USER_ID_KEY, invalid_user_id)

    with pytest.raises(AppError) as caught:
        service.require_user(session_store=store)

    assert caught.value.error_code == "UNAUTHORIZED"

    if invalid_user_id is None:
        # Khách chưa đăng nhập được giữ giỏ hàng tạm.
        assert store.get(CART_SESSION_KEY) == [{"product_id": 7}]
    else:
        # ID hỏng phải làm sạch toàn bộ trạng thái riêng tư.
        assert store.data == {}


def test_nonexistent_id_invalidates_session(
    test_db: Connection,
) -> None:
    """ID kiểu int nhưng không có trong users cũng phải bị chặn."""

    max_id = test_db.execute(
        text("SELECT COALESCE(MAX(id), 0) FROM users")
    ).scalar_one()
    missing_id = int(max_id) + 10000

    store = StrictSessionStore()
    store.set(AUTH_SESSION_USER_ID_KEY, missing_id)
    store.set(CHECKOUT_SESSION_KEY, "checkout-old")

    with pytest.raises(AppError) as caught:
        _service(test_db).require_user(session_store=store)

    assert caught.value.error_code == "UNAUTHORIZED"
    assert store.data == {}


def test_locking_logged_in_user_invalidates_session(
    test_db: Connection,
) -> None:
    """Admin khóa tài khoản sau login: require_user phải xóa phiên."""

    service = _service(test_db)
    registered = _register(service, _email())
    store = StrictSessionStore()

    service.login(
        email=registered.email,
        password=PASSWORD,
        session_store=store,
    )
    store.set(CART_SESSION_KEY, [{"product_id": 7}])
    _lock(test_db, registered.user_id)

    with pytest.raises(AppError) as caught:
        service.require_user(session_store=store)

    assert caught.value.error_code == "ACCOUNT_LOCKED"
    assert store.data == {}


def test_logout_does_not_affect_another_user(
    test_db: Connection,
) -> None:
    """Hai phiên độc lập, logout một phiên không xóa phiên kia."""

    service = _service(test_db)
    first = _register(service, _email())
    second = _register(service, _email())
    first_store = StrictSessionStore()
    second_store = StrictSessionStore()

    service.login(
        email=first.email,
        password=PASSWORD,
        session_store=first_store,
    )
    service.login(
        email=second.email,
        password=PASSWORD,
        session_store=second_store,
    )

    service.logout(session_store=first_store)

    assert first_store.data == {}
    current = service.require_user(
        session_store=second_store,
        allowed_roles={"CUSTOMER"},
    )
    assert current.user_id == second.user_id
    assert current.user_id != first.user_id


def test_role_change_is_enforced_on_existing_session(
    test_db: Connection,
) -> None:
    """Role hiện tại phải được tải lại từ MariaDB mỗi lần guard."""

    service = _service(test_db)
    registered = _register(service, _email())
    store = StrictSessionStore()

    service.login(
        email=registered.email,
        password=PASSWORD,
        session_store=store,
    )
    test_db.execute(
        text("UPDATE users SET role = 'ADMIN' WHERE id = :id"),
        {"id": registered.user_id},
    )

    current = service.require_user(
        session_store=store,
        allowed_roles={"ADMIN"},
    )
    assert current.role == "ADMIN"
    assert store.data == {
        AUTH_SESSION_USER_ID_KEY: registered.user_id
    }

    with pytest.raises(AppError) as caught:
        service.require_user(
            session_store=store,
            allowed_roles={"CUSTOMER"},
        )

    assert caught.value.error_code == "FORBIDDEN"
    # Thiếu quyền không có nghĩa là phải đăng xuất.
    assert store.get(AUTH_SESSION_USER_ID_KEY) == registered.user_id
