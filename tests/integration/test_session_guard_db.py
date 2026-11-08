
"""US02 Task 14 - Integration Test cho session guard.

Chỉ kết nối phone_shop_test thông qua fixture test_db.
Dữ liệu thử được rollback sau mỗi bài test.
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


class MemorySessionStore:
    """Session phía server giả lập để kiểm thử."""

    def __init__(self):
        self.data = {}

    def set(self, key, value):
        self.data[key] = value

    def get(self, key):
        return self.data.get(key)

    def remove(self, key):
        self.data.pop(key, None)


def _email() -> str:
    return f"task14_{token_hex(6)}@example.test"


def _service(connection: Connection) -> AuthService:
    """AuthService dùng đúng kết nối kiểm thử."""

    def session_factory() -> Session:
        return Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
        )

    return AuthService(
        session_factory=session_factory,
    )


def _register_and_login(
    connection: Connection,
):
    """Tạo Customer mới và đăng nhập trên DB test."""

    service = _service(connection)
    email = _email()

    registered = service.register(
        email=email,
        password=PASSWORD,
        confirm_password=PASSWORD,
        full_name="Nguyễn Văn A",
        phone="0912345678",
    )

    store = MemorySessionStore()

    service.login(
        email=email,
        password=PASSWORD,
        session_store=store,
    )

    return service, registered, store


def _fill_private_state(store):
    """Dữ liệu tạm cần được xóa khi đăng xuất."""

    store.set(CART_SESSION_KEY, [{"product_id": 10}])
    store.set(CHECKOUT_SESSION_KEY, "checkout-task14")
    store.set(
        USER_CACHE_SESSION_KEY,
        {"full_name": "Nguyễn Văn A"},
    )


def test_require_user_active_with_real_database(
    test_db: Connection,
) -> None:
    """Sau login, require_user đọc tài khoản ACTIVE từ DB."""

    service, registered, store = _register_and_login(
        test_db
    )

    current = service.require_user(
        session_store=store,
        allowed_roles={"CUSTOMER"},
    )

    assert current.user_id == registered.user_id
    assert current.email == registered.email
    assert current.role == "CUSTOMER"
    assert current.status == "ACTIVE"

    assert store.get(
        AUTH_SESSION_USER_ID_KEY
    ) == registered.user_id


def test_account_locked_after_login_loses_session(
    test_db: Connection,
) -> None:
    """Khóa tài khoản sau login phải chặn thao tác kế tiếp."""

    service, registered, store = _register_and_login(
        test_db
    )
    _fill_private_state(store)

    # Admin khóa tài khoản sau khi user đã đăng nhập.
    test_db.execute(
        text("""
            UPDATE users
            SET
                status = 'LOCKED',
                lock_reason = 'Task 14 integration test'
            WHERE id = :user_id
        """),
        {"user_id": registered.user_id},
    )

    with pytest.raises(AppError) as caught:
        service.require_user(session_store=store)

    assert caught.value.error_code == "ACCOUNT_LOCKED"

    # Danh tính, cart, checkout key và cache đều bị xóa.
    assert store.data == {}


def test_role_change_is_enforced_from_database(
    test_db: Connection,
) -> None:
    """Đổi role sau login phải có hiệu lực ngay."""

    service, registered, store = _register_and_login(
        test_db
    )

    # Ban đầu tài khoản là CUSTOMER.
    customer = service.require_user(
        session_store=store,
        allowed_roles={"CUSTOMER"},
    )

    assert customer.role == "CUSTOMER"

    # Mô phỏng quản trị thay role trong DB test.
    test_db.execute(
        text("""
            UPDATE users
            SET role = 'ADMIN'
            WHERE id = :user_id
        """),
        {"user_id": registered.user_id},
    )

    # Role cũ không được tiếp tục sử dụng.
    with pytest.raises(AppError) as caught:
        service.require_user(
            session_store=store,
            allowed_roles={"CUSTOMER"},
        )

    assert caught.value.error_code == "FORBIDDEN"

    # Role mới từ DB được áp dụng.
    admin = service.require_user(
        session_store=store,
        allowed_roles={"ADMIN"},
    )

    assert admin.role == "ADMIN"
    assert admin.user_id == registered.user_id


def test_nonexistent_user_id_invalidates_session(
    test_db: Connection,
) -> None:
    """Session trỏ tới ID không tồn tại phải bị từ chối."""

    service = _service(test_db)
    store = MemorySessionStore()

    maximum_id = test_db.execute(
        text("""
            SELECT COALESCE(MAX(id), 0)
            FROM users
        """)
    ).scalar_one()

    missing_id = int(maximum_id) + 10000

    store.set(AUTH_SESSION_USER_ID_KEY, missing_id)
    _fill_private_state(store)

    with pytest.raises(AppError) as caught:
        service.require_user(session_store=store)

    assert caught.value.error_code == "UNAUTHORIZED"
    assert store.data == {}


def test_logout_clears_user_state_after_real_login(
    test_db: Connection,
) -> None:
    """Logout xóa toàn bộ trạng thái riêng của người dùng."""

    service, registered, store = _register_and_login(
        test_db
    )

    _fill_private_state(store)
    store.set("phone_shop.ui.theme", "dark")

    assert store.get(
        AUTH_SESSION_USER_ID_KEY
    ) == registered.user_id

    service.logout(session_store=store)

    assert store.data == {
        "phone_shop.ui.theme": "dark",
    }

    # Sau logout, không thể sử dụng lại phiên cũ.
    with pytest.raises(AppError) as caught:
        service.require_user(session_store=store)

    assert caught.value.error_code == "UNAUTHORIZED"


def test_logout_one_session_does_not_affect_another(
    test_db: Connection,
) -> None:
    """Mỗi Session Store giữ danh tính độc lập."""

    service = _service(test_db)

    first_email = _email()
    second_email = _email()

    first = service.register(
        email=first_email,
        password=PASSWORD,
        confirm_password=PASSWORD,
        full_name="Khách hàng thứ nhất",
        phone="0912345678",
    )

    second = service.register(
        email=second_email,
        password=PASSWORD,
        confirm_password=PASSWORD,
        full_name="Khách hàng thứ hai",
        phone="0987654321",
    )

    first_store = MemorySessionStore()
    second_store = MemorySessionStore()

    service.login(
        email=first_email,
        password=PASSWORD,
        session_store=first_store,
    )

    service.login(
        email=second_email,
        password=PASSWORD,
        session_store=second_store,
    )

    service.logout(session_store=first_store)

    assert first_store.get(
        AUTH_SESSION_USER_ID_KEY
    ) is None

    assert second_store.get(
        AUTH_SESSION_USER_ID_KEY
    ) == second.user_id

    # Session thứ hai vẫn xác thực bình thường.
    current = service.require_user(
        session_store=second_store,
        allowed_roles={"CUSTOMER"},
    )

    assert current.user_id == second.user_id
    assert current.user_id != first.user_id
