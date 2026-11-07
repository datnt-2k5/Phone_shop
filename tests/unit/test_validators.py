
"""Task 10 - Unit Test dữ liệu đăng ký."""

import pytest

from models.app_error import AppError
from utils.validators import (
    validate_confirm_password,
    validate_email,
    validate_full_name,
    validate_password,
    validate_phone,
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "  NGUYEN.VANA+SHOP@GMAIL.COM  ",
            "nguyen.vana+shop@gmail.com",
        ),
        (
            "user@example.com",
            "user@example.com",
        ),
    ],
)
def test_email_normalizes(source, expected):
    assert validate_email(source) == expected


@pytest.mark.parametrize(
    "source",
    [
        "",
        "khong-hop-le",
        "a@",
        "name..last@example.com",
        "x@-example.com",
        "x@example..com",
        "a" * 95 + "@example.com",
    ],
)
def test_email_invalid(source):
    with pytest.raises(AppError) as caught:
        validate_email(source)

    assert "email" in caught.value.errors


def test_full_name_normalizes():
    assert (
        validate_full_name("  Nguyễn   Văn  A  ")
        == "Nguyễn Văn A"
    )


@pytest.mark.parametrize(
    "source",
    [
        "",
        "   ",
        "A" * 101,
    ],
)
def test_full_name_invalid(source):
    with pytest.raises(AppError) as caught:
        validate_full_name(source)

    assert "full_name" in caught.value.errors


@pytest.mark.parametrize(
    "source",
    [
        "0123456789",
        "0987654321",
    ],
)
def test_phone_valid(source):
    assert validate_phone(source) == source


@pytest.mark.parametrize(
    "source",
    [
        "1234567890",
        "012345678",
        "01234567890",
        "0abcdefghi",
        "0١٢٣٤٥٦٧٨٩",
    ],
)
def test_phone_invalid(source):
    with pytest.raises(AppError) as caught:
        validate_phone(source)

    assert "phone" in caught.value.errors


@pytest.mark.parametrize(
    "source",
    [
        "Abcdefg1",
        "A1" + "a" * 70,
        "A1" + "é" * 35,
    ],
)
def test_password_valid(source):
    assert validate_password(source) == source


@pytest.mark.parametrize(
    "source",
    [
        "abc123",
        "abcdefgh",
        "12345678",
        "A1" + "a" * 71,
        "A1" + "é" * 36,
    ],
)
def test_password_invalid(source):
    with pytest.raises(AppError) as caught:
        validate_password(source)

    assert "password" in caught.value.errors


def test_confirm_password_equal():
    assert (
        validate_confirm_password(
            "Abcdefg1",
            "Abcdefg1",
        )
        is None
    )


@pytest.mark.parametrize(
    "confirmation",
    [
        "Khac1234",
        "abcdefg1",
        "",
        None,
    ],
)
def test_confirm_password_invalid(confirmation):
    with pytest.raises(AppError) as caught:
        validate_confirm_password(
            "Abcdefg1",
            confirmation,
        )

    assert "confirm_password" in caught.value.errors


@pytest.mark.parametrize(
    ("validator", "source", "field"),
    [
        (validate_email, None, "email"),
        (validate_full_name, 123, "full_name"),
        (validate_phone, None, "phone"),
        (validate_password, 123, "password"),
    ],
)
def test_invalid_types(validator, source, field):
    with pytest.raises(AppError) as caught:
        validator(source)

    assert field in caught.value.errors
