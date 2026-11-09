
"""US04 Task 23: kiểm tra Route Guard với role từ phone_shop_test."""

from secrets import token_hex

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from models.app_error import AppError
from services.auth_service import AuthService
from services.auth_session import AUTH_SESSION_USER_ID_KEY
from ui.navigation import menu_for_role
from ui.route_guard import RouteStatus, check_route_access

PASSWORD = "MatKhau123!"


class StrictSessionStore:
    """Mô phỏng Flet Session, không dùng tài khoản thật."""

    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value

    def remove(self, key):
        self.data.pop(key, None)


def session_factory(connection: Connection):
    """Tạo SQLAlchemy Session trong transaction kiểm thử."""

    def create_session() -> Session:
        return Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
        )

    return create_session


@pytest.fixture
def account(test_db: Connection):
    """Tạo Customer thử nghiệm trong phone_shop_test."""

    auth = AuthService(
        session_factory=session_factory(test_db),
    )

    email = f"task23_{token_hex(8)}@example.test"

    registered = auth.register(
        email=email,
        password=PASSWORD,
        confirm_password=PASSWORD,
        full_name="Khách hàng Test",
        phone="0912345678",
    )

    store = StrictSessionStore()

    auth.login(
        email=email,
        password=PASSWORD,
        session_store=store,
    )

    return {
        "auth": auth,
        "store": store,
        "db": test_db,
        "id": registered.user_id,
    }


def access_as_current_user(account, route):
    """Lấy role thật từ database trước khi kiểm tra route."""

    user = account["auth"].require_user(
        session_store=account["store"],
    )

    return check_route_access(
        route=route,
        role=user.role,
    )


def set_role(account, role):
    """Chỉ sửa role của tài khoản trong database test."""

    account["db"].execute(
        text("""
            UPDATE users
            SET role = :role
            WHERE id = :id
        """),
        {
            "role": role,
            "id": account["id"],
        },
    )


def test_customer_is_blocked_from_admin_pages(account):
    """Customer không thể mở URL Admin và Super Admin."""

    for route in (
        "/admin/dashboard",
        "/admin/orders",
        "/super/accounts",
    ):
        result = access_as_current_user(
            account,
            route,
        )

        assert result.status == RouteStatus.FORBIDDEN

    assert access_as_current_user(
        account,
        "/profile",
    ).status == RouteStatus.ALLOW


def test_admin_can_open_admin_but_not_super_pages(account):
    """Admin được vào /admin nhưng bị chặn /super."""

    set_role(account, "ADMIN")

    assert access_as_current_user(
        account,
        "/admin/dashboard",
    ).status == RouteStatus.ALLOW

    assert access_as_current_user(
        account,
        "/super/accounts",
    ).status == RouteStatus.FORBIDDEN

    assert "/super/accounts" not in {
        item.route
        for item in menu_for_role("ADMIN")
    }


def test_super_admin_can_access_super_pages(account):
    """Super Admin được mở cả /admin và /super."""

    set_role(account, "SUPER_ADMIN")

    for route in (
        "/admin/dashboard",
        "/super/accounts",
        "/super/settings",
    ):
        result = access_as_current_user(
            account,
            route,
        )

        assert result.status == RouteStatus.ALLOW


def test_role_change_is_applied_on_next_check(account):
    """Đổi role trong database phải có hiệu lực lần kiểm tra sau."""

    assert access_as_current_user(
        account,
        "/admin/dashboard",
    ).status == RouteStatus.FORBIDDEN

    set_role(account, "ADMIN")

    assert access_as_current_user(
        account,
        "/admin/dashboard",
    ).status == RouteStatus.ALLOW

    set_role(account, "CUSTOMER")

    assert access_as_current_user(
        account,
        "/admin/dashboard",
    ).status == RouteStatus.FORBIDDEN


def test_forged_role_in_session_does_not_change_permissions(
    account,
):
    """Giả mạo role trong Session cache không được cấp quyền."""

    account["store"].set(
        "phone_shop.auth.role",
        "SUPER_ADMIN",
    )

    result = access_as_current_user(
        account,
        "/super/settings",
    )

    assert result.status == RouteStatus.FORBIDDEN


def test_locked_user_loses_session(account):
    """Khóa tài khoản thì lần kiểm tra kế tiếp bị từ chối."""

    account["db"].execute(
        text("""
            UPDATE users
            SET
                status = 'LOCKED',
                lock_reason = 'Task 23 test'
            WHERE id = :id
        """),
        {"id": account["id"]},
    )

    with pytest.raises(AppError) as caught:
        account["auth"].require_user(
            session_store=account["store"],
        )

    assert caught.value.error_code == "ACCOUNT_LOCKED"

    assert account["store"].get(
        AUTH_SESSION_USER_ID_KEY
    ) is None

    # Không còn user hợp lệ -> main.py xem là Guest.
    result = check_route_access(
        route="/profile",
        role="GUEST",
    )

    assert result.status == RouteStatus.LOGIN_REQUIRED
    assert result.redirect_to == "/login"


def test_guest_direct_url_is_redirected_to_login():
    """Guest gõ thẳng URL /admin cũng không được vào."""

    result = check_route_access(
        route="/admin/products",
        role="GUEST",
    )

    assert result.status == RouteStatus.LOGIN_REQUIRED
    assert result.redirect_to == "/login"
