
"""Unit Test giao diện đăng nhập - US02 Task 15.

Không kết nối MariaDB hoặc mở trình duyệt.
"""

from models.app_error import AppError
from services.auth_service import LoginResult
from ui.pages.login_page import LoginForm


def _result() -> LoginResult:
    """Kết quả đăng nhập giả lập."""

    return LoginResult(
        user_id=42,
        email="test@example.com",
        full_name="Nguyễn Văn A",
        role="CUSTOMER",
    )


def _make_form(login_action):
    """Tạo form và lưu các sự kiện để kiểm tra."""

    successes = []
    notifications = []

    form = LoginForm(
        login_action=login_action,
        on_success=lambda result: successes.append(result),
        notify_user=lambda message, error: (
            notifications.append((message, error))
        ),
        refresh=lambda: None,
    )

    return form, successes, notifications


def _fill_valid(form: LoginForm) -> None:
    form.email.value = "test@example.com"
    form.password.value = "MatKhau123!"


def test_login_form_has_two_fields():
    """Form có email, mật khẩu được ẩn và nút đăng nhập."""

    form, _, _ = _make_form(
        lambda **kwargs: _result()
    )

    assert form.email.label == "Email *"
    assert form.password.label == "Mật khẩu *"
    assert form.password.password is True
    assert form.password.can_reveal_password is True
    assert form.submit_button.disabled is not True


def test_empty_form_does_not_call_service():
    """Form trống phải hiển thị lỗi, không gọi AuthService."""

    calls = []

    def fake_login(**kwargs):
        calls.append(kwargs)
        return _result()

    form, successes, _ = _make_form(fake_login)

    form.submit()

    assert calls == []
    assert successes == []
    assert form.email_error.visible is True
    assert form.password_error.visible is True
    assert form.feedback.visible is True


def test_wrong_password_shows_generic_message():
    """Sai mật khẩu: hiển thị lỗi chung, không điều hướng."""

    def fake_login(**kwargs):
        raise AppError(
            "INVALID_CREDENTIALS",
            "Email hoặc mật khẩu không đúng.",
        )

    form, successes, notifications = _make_form(fake_login)
    _fill_valid(form)

    form.submit()

    assert successes == []
    assert form.feedback.visible is True
    assert form.feedback.value == (
        "Email hoặc mật khẩu không đúng."
    )
    assert notifications[-1][1] is True
    assert form.password.value == ""
    assert form.submit_button.disabled is False


def test_locked_account_shows_error():
    """Tài khoản bị khóa không được điều hướng."""

    def fake_login(**kwargs):
        raise AppError(
            "ACCOUNT_LOCKED",
            "Tài khoản đã bị khóa hoặc không còn hoạt động.",
        )

    form, successes, notifications = _make_form(fake_login)
    _fill_valid(form)

    form.submit()

    assert successes == []
    assert "bị khóa" in form.feedback.value
    assert notifications[-1][1] is True


def test_success_calls_service_and_callback():
    """Đăng nhập thành công gọi callback với role từ Service."""

    calls = []

    def fake_login(**kwargs):
        calls.append(kwargs)
        return _result()

    form, successes, notifications = _make_form(fake_login)
    _fill_valid(form)

    form.submit()

    assert len(calls) == 1
    assert calls[0] == {
        "email": "test@example.com",
        "password": "MatKhau123!",
    }

    assert len(successes) == 1
    assert successes[0].user_id == 42
    assert successes[0].role == "CUSTOMER"
    assert notifications == []
    assert form.password.value == ""
    assert form.submit_button.disabled is False


def test_unexpected_error_does_not_leak_details():
    """Lỗi nội bộ không được lộ thông tin nhạy cảm."""

    def fake_login(**kwargs):
        raise RuntimeError("SECRET_DATABASE_PASSWORD")

    form, successes, notifications = _make_form(fake_login)
    _fill_valid(form)

    form.submit()

    assert successes == []
    assert form.feedback.visible is True
    assert "SECRET_DATABASE_PASSWORD" not in (
        form.feedback.value
    )
    assert "SECRET_DATABASE_PASSWORD" not in (
        notifications[-1][0]
    )
    assert notifications[-1][1] is True
    assert form.submit_button.disabled is False


def test_repeated_submit_is_blocked_while_busy():
    """Không gửi hai yêu cầu đồng thời từ cùng một form."""

    calls = []
    holder = {}

    def fake_login(**kwargs):
        calls.append(kwargs)

        # Thử submit lần thứ hai khi lần đầu còn chạy.
        holder["form"].submit()

        return _result()

    form, successes, _ = _make_form(fake_login)
    holder["form"] = form
    _fill_valid(form)

    form.submit()

    assert len(calls) == 1
    assert len(successes) == 1
    assert form.submit_button.disabled is False


def test_editing_email_clears_old_error():
    """Khi sửa email, thông báo lỗi cũ được ẩn."""

    form, _, _ = _make_form(
        lambda **kwargs: _result()
    )

    form.submit()
    assert form.email_error.visible is True

    form.email.value = "new@example.com"
    form.clear_field_error("email")

    assert form.email_error.visible is False
    assert form.email_error.value == ""
    assert form.feedback.visible is False
