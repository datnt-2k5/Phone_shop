
"""Unit Test giao diện đăng ký Flet - Task 11.

Không ghi dữ liệu MariaDB.
"""


from models.app_error import AppError
from services.auth_service import RegistrationResult
from ui.pages.register_page import RegistrationForm


def _registration_result() -> RegistrationResult:
    return RegistrationResult(
        user_id=123,
        email="test@example.com",
        full_name="Nguyễn Văn A",
        phone="0912345678",
        role="CUSTOMER",
        status="ACTIVE",
    )


def _make_form(register_action):
    """Tạo form với Service và thông báo giả lập."""

    notifications = []

    form = RegistrationForm(
        register_action=register_action,
        notify_user=lambda message, error: (
            notifications.append((message, error))
        ),
        refresh=lambda: None,
    )

    return form, notifications


def _fill_valid(form: RegistrationForm) -> None:
    """Điền dữ liệu hợp lệ cho form."""

    form.full_name.value = "Nguyễn Văn A"
    form.email.value = "test@example.com"
    form.phone.value = "0912345678"
    form.password.value = "MatKhau123!"
    form.confirm_password.value = "MatKhau123!"


def test_form_has_required_fields_and_hidden_passwords():
    """Form có đủ 5 trường, không cho người dùng chọn role."""

    form, _ = _make_form(
        lambda **kwargs: _registration_result()
    )

    assert set(form.fields) == {
        "full_name",
        "email",
        "phone",
        "password",
        "confirm_password",
    }

    assert "role" not in form.fields
    assert form.password.password is True
    assert form.confirm_password.password is True
    assert form.password.can_reveal_password is True


def test_empty_form_shows_field_errors():
    """Nhấn đăng ký khi trống phải báo lỗi ở từng trường."""

    calls = []

    def fake_register(**kwargs):
        calls.append(kwargs)
        return _registration_result()

    form, _ = _make_form(fake_register)

    form.submit()

    assert calls == []

    for field in (
        "full_name",
        "email",
        "phone",
        "password",
        "confirm_password",
    ):
        assert form.error_labels[field].visible is True
        assert form.error_labels[field].value

    assert form.feedback.visible is True


def test_password_confirmation_mismatch_blocks_registration():
    """Xác nhận sai không được gọi Service."""

    calls = []

    def fake_register(**kwargs):
        calls.append(kwargs)
        return _registration_result()

    form, _ = _make_form(fake_register)
    _fill_valid(form)

    form.confirm_password.value = "KhacMatKhau123!"
    form.submit()

    assert calls == []
    assert form.error_labels[
        "confirm_password"
    ].visible is True


def test_password_over_72_bytes_is_blocked_on_ui():
    """Mật khẩu hơn 72 byte UTF-8 không qua được UI."""

    calls = []

    def fake_register(**kwargs):
        calls.append(kwargs)
        return _registration_result()

    form, _ = _make_form(fake_register)
    _fill_valid(form)

    long_password = "A1" + "é" * 36

    assert len(long_password.encode("utf-8")) > 72

    form.password.value = long_password
    form.confirm_password.value = long_password
    form.submit()

    assert calls == []
    assert form.error_labels["password"].visible is True


def test_success_calls_service_and_clears_sensitive_fields():
    """Đăng ký hợp lệ gọi Service và xóa dữ liệu form."""

    calls = []

    def fake_register(**kwargs):
        calls.append(kwargs)
        return _registration_result()

    form, notifications = _make_form(fake_register)
    _fill_valid(form)

    form.submit()

    assert len(calls) == 1
    assert calls[0]["email"] == "test@example.com"
    assert calls[0]["password"] == "MatKhau123!"
    assert calls[0]["confirm_password"] == "MatKhau123!"

    assert form.password.value == ""
    assert form.confirm_password.value == ""
    assert form.email.value == ""

    assert form.feedback.visible is True
    assert form.feedback.value.startswith(
        "Tạo tài khoản thành công"
    )

    assert notifications
    assert notifications[-1][1] is False
    assert form.submit_button.disabled is False


def test_duplicate_email_shows_error():
    """Email trùng phải hiện lỗi bên dưới ô Email."""

    def fake_register(**kwargs):
        raise AppError(
            "EMAIL_EXISTS",
            "Email đã được sử dụng.",
            {"email": "Email đã tồn tại."},
        )

    form, notifications = _make_form(fake_register)
    _fill_valid(form)

    form.submit()

    assert form.error_labels["email"].visible is True
    assert (
        form.error_labels["email"].value
        == "Email đã tồn tại."
    )
    assert notifications[-1][1] is True
    assert form.email.value == "test@example.com"


def test_unexpected_backend_error_is_generic():
    """Không tiết lộ thông tin nội bộ khi Service gặp lỗi."""

    def fake_register(**kwargs):
        raise RuntimeError("SECRET_DATABASE_PASSWORD")

    form, notifications = _make_form(fake_register)
    _fill_valid(form)

    form.submit()

    assert form.feedback.visible is True
    assert "SECRET_DATABASE_PASSWORD" not in (
        form.feedback.value
    )
    assert "SECRET_DATABASE_PASSWORD" not in (
        notifications[-1][0]
    )
    assert notifications[-1][1] is True
    assert form.submit_button.disabled is False


def test_editing_field_clears_its_error():
    """Sau khi sửa email, ẩn lỗi cũ của trường đó."""

    form, _ = _make_form(
        lambda **kwargs: _registration_result()
    )

    form.submit()

    assert form.error_labels["email"].visible is True

    form.email.value = "test@example.com"
    form.clear_error("email")

    assert form.error_labels["email"].visible is False
    assert form.error_labels["email"].value == ""
