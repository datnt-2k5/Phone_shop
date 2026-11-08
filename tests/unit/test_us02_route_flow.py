
"""Task 16: kiểm thử UI đăng nhập và quy tắc điều hướng.

Chỉ dùng đối tượng giả lập; không mở MariaDB.
"""

import pytest

from models.app_error import AppError
from services.auth_service import AuthService, LoginResult
from services.auth_session import AUTH_SESSION_USER_ID_KEY
from ui.navigation import home_route_for_role, route_available
from ui.pages.login_page import LoginForm


class StrictSessionStore:
    """Giả lập Flet: remove() báo KeyError khi thiếu khóa."""

    def __init__(self) -> None:
        self.data: dict[str, object] = {}

    def set(self, key: str, value: object) -> None:
        self.data[key] = value

    def get(self, key: str) -> object | None:
        return self.data.get(key)

    def remove(self, key: str) -> None:
        self.data.pop(key)


def _make_form(login_action):
    """Tạo form, ghi lại điều hướng và thông báo."""

    destinations: list[str] = []
    notifications: list[tuple[str, bool]] = []

    form = LoginForm(
        login_action=login_action,
        on_success=lambda result: destinations.append(
            home_route_for_role(result.role)
        ),
        notify_user=lambda message, error: notifications.append(
            (message, error)
        ),
        refresh=lambda: None,
    )
    return form, destinations, notifications


def _fill_form(form: LoginForm) -> None:
    form.email.value = "  TEST@EXAMPLE.COM  "
    form.password.value = "MatKhau123!"


@pytest.mark.parametrize(
    ("role", "destination"),
    [
        ("CUSTOMER", "/profile"),
        ("ADMIN", "/admin/dashboard"),
        ("SUPER_ADMIN", "/super/accounts"),
    ],
)
def test_login_success_goes_to_verified_role(
    role: str,
    destination: str,
) -> None:
    """UI chỉ dựa trên role do Service trả về, không tự cấp role."""

    received: list[dict[str, str]] = []

    def fake_login(**kwargs):
        received.append(kwargs)
        return LoginResult(
            user_id=42,
            email="test@example.com",
            full_name="Nguyễn Văn A",
            role=role,
        )

    form, destinations, notifications = _make_form(fake_login)
    _fill_form(form)
    form.submit()

    assert destinations == [destination]
    assert notifications == []
    assert len(received) == 1
    assert set(received[0]) == {"email", "password"}
    assert received[0]["password"] == "MatKhau123!"
    assert form.password.value == ""


@pytest.mark.parametrize(
    ("error_code", "message"),
    [
        ("INVALID_CREDENTIALS", "Email hoặc mật khẩu không đúng."),
        (
            "ACCOUNT_LOCKED",
            "Tài khoản đã bị khóa hoặc không còn hoạt động.",
        ),
    ],
)
def test_failed_login_never_navigates(
    error_code: str,
    message: str,
) -> None:
    """Đăng nhập sai hoặc LOCKED chỉ thông báo lỗi."""

    def reject_login(**kwargs):
        raise AppError(error_code, message)

    form, destinations, notifications = _make_form(reject_login)
    _fill_form(form)
    form.submit()

    assert destinations == []
    assert form.feedback.value == message
    assert form.feedback.visible is True
    assert notifications[-1] == (message, True)
    assert form.password.value == ""


def test_empty_login_does_not_call_service() -> None:
    """Form trống không được phát sinh yêu cầu đăng nhập."""

    def forbidden_login(**kwargs):
        raise AssertionError("Không được gọi Service khi form trống")

    form, destinations, _ = _make_form(forbidden_login)
    form.submit()

    assert destinations == []
    assert form.email_error.visible is True
    assert form.password_error.visible is True


@pytest.mark.parametrize(
    ("role", "route"),
    [
        ("GUEST", "/profile"),
        ("GUEST", "/admin/dashboard"),
        ("CUSTOMER", "/admin/dashboard"),
        ("CUSTOMER", "/super/accounts"),
        ("ADMIN", "/super/accounts"),
        ("SUPER_ADMIN", "/login"),
    ],
)
def test_unauthorized_route_is_not_visible(
    role: str,
    route: str,
) -> None:
    """Ẩn route bảo vệ khi vai trò không phù hợp."""

    assert route_available(role, route) is False


def test_logout_handles_flet_missing_keys_twice() -> None:
    """Flet thật báo KeyError khi remove khóa chưa tồn tại."""

    store = StrictSessionStore()
    store.set(AUTH_SESSION_USER_ID_KEY, 42)
    store.set("phone_shop.ui.theme", "dark")

    AuthService.logout(session_store=store)
    AuthService.logout(session_store=store)

    assert store.data == {"phone_shop.ui.theme": "dark"}


def test_guest_cannot_see_protected_role_from_ui() -> None:
    """Trạng thái Guest không có đường đến trang quản trị."""

    assert not route_available("GUEST", "/profile")
    assert not route_available("GUEST", "/admin/dashboard")
    assert not route_available("GUEST", "/super/accounts")
