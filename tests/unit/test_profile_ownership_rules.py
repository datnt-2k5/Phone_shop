
"""US03 Task 19 - Unit Test quyền OWN và trường được bảo vệ.

Không kết nối MariaDB.
Kiểm tra hợp đồng API và các quy tắc validation.
"""

import inspect
from dataclasses import fields

import pytest

from models.app_error import AppError
from repositories.user_repository import UserRepository
from services.profile_service import ProfileResult, ProfileService
from utils.validators import (
    validate_address,
    validate_full_name,
    validate_phone,
)


def test_get_profile_api_does_not_accept_target_user_id() -> None:
    """Hàm xem hồ sơ không cho client chọn ID người khác."""

    signature = inspect.signature(
        ProfileService.get_my_profile
    )

    assert list(signature.parameters) == [
        "self",
        "session_store",
    ]


def test_update_profile_api_has_only_three_editable_fields() -> None:
    """Hàm cập nhật chỉ nhận 3 trường sửa được và session."""

    signature = inspect.signature(
        ProfileService.update_my_profile
    )

    assert list(signature.parameters) == [
        "self",
        "session_store",
        "full_name",
        "phone",
        "address",
    ]

    # Các tham số ngoài self đều phải truyền bằng keyword.
    for name in (
        "session_store",
        "full_name",
        "phone",
        "address",
    ):
        assert signature.parameters[name].kind == (
            inspect.Parameter.KEYWORD_ONLY
        )


@pytest.mark.parametrize(
    "forbidden_field",
    [
        "user_id",
        "id",
        "email",
        "role",
        "status",
        "password_hash",
        "updated_at",
        "updated_by",
    ],
)
def test_forged_field_is_rejected_by_service_api(
    forbidden_field: str,
) -> None:
    """Gửi trường không được phép phải bị từ chối."""

    # Không mở database: Python từ chối tham số ngay
    # tại thời điểm gọi hàm.
    service = ProfileService(
        session_factory=lambda: None,
    )

    payload = {
        "full_name": "Nguyễn Văn A",
        "phone": "0912345678",
        "address": "Đà Nẵng",
        forbidden_field: "FORGED_VALUE",
    }

    with pytest.raises(TypeError) as caught:
        service.update_my_profile(
            session_store=None,
            **payload,
        )

    assert forbidden_field in str(caught.value)


@pytest.mark.parametrize(
    ("field", "value", "validator"),
    [
        (
            "full_name",
            "   ",
            validate_full_name,
        ),
        (
            "full_name",
            "A" * 101,
            validate_full_name,
        ),
        (
            "full_name",
            None,
            validate_full_name,
        ),
        (
            "phone",
            "1234567890",
            validate_phone,
        ),
        (
            "phone",
            "0" + "\u0661" * 9,
            validate_phone,
        ),
        (
            "phone",
            123,
            validate_phone,
        ),
        (
            "address",
            "A" * 256,
            validate_address,
        ),
        (
            "address",
            123,
            validate_address,
        ),
    ],
)
def test_invalid_profile_field_has_correct_error(
    field: str,
    value: object,
    validator,
) -> None:
    """Dữ liệu sai phải báo đúng trường và mã lỗi."""

    with pytest.raises(AppError) as caught:
        validator(value)

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert field in caught.value.errors


def test_address_exactly_255_characters_is_valid() -> None:
    """Giới hạn của address là 255 ký tự."""

    address = "A" * 255

    assert validate_address(address) == address
    assert len(validate_address(address)) == 255


def test_profile_result_does_not_expose_password() -> None:
    """Dữ liệu trả về không chứa mật khẩu hoặc hash."""

    result_fields = {
        item.name
        for item in fields(ProfileResult)
    }

    assert "password" not in result_fields
    assert "password_hash" not in result_fields

    assert {
        "user_id",
        "email",
        "role",
        "status",
        "full_name",
        "phone",
        "address",
    }.issubset(result_fields)


def test_repository_update_has_no_sensitive_field_params() -> None:
    """Repository cũng không nhận email, role hoặc status."""

    signature = inspect.signature(
        UserRepository.update_own_profile
    )

    assert set(signature.parameters) == {
        "self",
        "user_id",
        "full_name",
        "phone",
        "address",
        "now_utc",
    }

    assert "email" not in signature.parameters
    assert "role" not in signature.parameters
    assert "status" not in signature.parameters
    assert "password_hash" not in signature.parameters
