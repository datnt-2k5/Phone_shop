
"""Task 12 / US01 - Unit tests for registration edge cases.

Does not connect to MariaDB or alter application data.
"""

import pytest

from models.app_error import AppError
from services.auth_service import AuthService, RegistrationResult
from ui.pages.register_page import RegistrationForm
from utils.validators import (
    validate_confirm_password,
    validate_email,
    validate_password,
)


@pytest.mark.parametrize(
    ("raw_email", "expected"),
    [
        ("  USER@EXAMPLE.COM  ", "user@example.com"),
        (
            "MiXeD.Case+Shop@Example.Test",
            "mixed.case+shop@example.test",
        ),
    ],
)
def test_valid_email_normalizes_case(
    raw_email: str,
    expected: str,
) -> None:
    assert validate_email(raw_email) == expected


@pytest.mark.parametrize(
    "password",
    [
        "A1" + "a" * 70,       # 72 ASCII bytes
        "A1" + "é" * 35,       # 2 + 35 * 2 = 72 UTF-8 bytes
        "A1" + "😀" * 17 + "zz",  # 2 + 17 * 4 + 2 = 72
    ],
)
def test_password_accepts_exactly_72_utf8_bytes(
    password: str,
) -> None:
    assert len(password.encode("utf-8")) == 72
    assert validate_password(password) == password


@pytest.mark.parametrize(
    "password",
    [
        "A1" + "a" * 71,   # 73 bytes
        "A1" + "é" * 36,   # 74 bytes
        "A1" + "😀" * 18,  # 74 bytes
    ],
)
def test_password_over_72_bytes_is_rejected(
    password: str,
) -> None:
    assert len(password.encode("utf-8")) > 72

    with pytest.raises(AppError) as caught:
        validate_password(password)

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert "password" in caught.value.errors


@pytest.mark.parametrize(
    "confirmation",
    [
        "matkhau123!",
        "MatKhau123! ",
        "",
    ],
)
def test_confirmation_must_match_exactly(
    confirmation: str,
) -> None:
    with pytest.raises(AppError) as caught:
        validate_confirm_password(
            "MatKhau123!",
            confirmation,
        )

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert "confirm_password" in caught.value.errors


def test_registration_form_never_sends_role() -> None:
    """UI collects only 5 allowed fields, not a client role."""

    submitted: list[dict[str, str]] = []

    def fake_register(**kwargs: str) -> RegistrationResult:
        submitted.append(kwargs)

        return RegistrationResult(
            user_id=123,
            email="unit@example.test",
            full_name="Nguyễn Văn A",
            phone="0912345678",
            role="CUSTOMER",
            status="ACTIVE",
        )

    form = RegistrationForm(
        register_action=fake_register,
        notify_user=lambda message, error: None,
        refresh=lambda: None,
    )

    form.full_name.value = "Nguyễn Văn A"
    form.email.value = "unit@example.test"
    form.phone.value = "0912345678"
    form.password.value = "MatKhau123!"
    form.confirm_password.value = "MatKhau123!"

    form.submit()

    assert "role" not in form.fields
    assert len(submitted) == 1

    assert set(submitted[0]) == {
        "full_name",
        "email",
        "phone",
        "password",
        "confirm_password",
    }


@pytest.mark.parametrize(
    "forged_role",
    ["ADMIN", "SUPER_ADMIN"],
)
def test_auth_service_rejects_client_supplied_role(
    forged_role: str,
) -> None:
    """Reject forged role before opening a database session."""

    def forbidden_session_factory():
        raise AssertionError(
            "A forged role must not open a DB session"
        )

    service = AuthService(
        session_factory=forbidden_session_factory
    )

    with pytest.raises(TypeError) as caught:
        service.register(
            email="forged@example.test",
            password="MatKhau123!",
            confirm_password="MatKhau123!",
            full_name="Nguyễn Văn A",
            phone="0912345678",
            role=forged_role,
        )

    assert "role" in str(caught.value)
