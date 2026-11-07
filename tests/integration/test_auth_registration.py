
"""Integration Test đăng ký tài khoản - US01 Task 9 và 10.

Chỉ sử dụng phone_shop_test.
Fixture test_db sẽ rollback dữ liệu sau mỗi bài test.
"""

from secrets import token_hex

import bcrypt
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from models.app_error import AppError
from services.auth_service import AuthService


def _make_service(connection: Connection) -> AuthService:
    """Tạo AuthService sử dụng kết nối kiểm thử."""

    def session_factory() -> Session:
        return Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
        )

    return AuthService(
        session_factory=session_factory,
    )


def _unique_email() -> str:
    """Tạo email riêng cho từng bài kiểm thử."""

    return f"task9_{token_hex(6)}@example.test"


def test_register_customer_success(
    test_db: Connection,
) -> None:
    """Đăng ký thành công với CUSTOMER/ACTIVE."""

    service = _make_service(test_db)
    email = _unique_email()
    password = "MatKhau123!"

    result = service.register(
        email=f"  {email.upper()}  ",
        password=password,
        confirm_password=password,
        full_name="Nguyễn Văn A",
        phone="0912345678",
    )

    # Kiểm tra kết quả trả về
    assert result.user_id > 0
    assert result.email == email
    assert result.full_name == "Nguyễn Văn A"
    assert result.phone == "0912345678"
    assert result.role == "CUSTOMER"
    assert result.status == "ACTIVE"

    # Kiểm tra dữ liệu lưu trong MariaDB
    row = test_db.execute(
        text("""
            SELECT
                id,
                email,
                password_hash,
                full_name,
                phone,
                role,
                status,
                created_at,
                updated_at
            FROM users
            WHERE id = :user_id
        """),
        {"user_id": result.user_id},
    ).mappings().one()

    assert row["email"] == email
    assert row["role"] == "CUSTOMER"
    assert row["status"] == "ACTIVE"
    assert row["phone"] == "0912345678"

    # Không lưu mật khẩu dạng văn bản
    assert row["password_hash"] != password
    assert row["password_hash"].startswith("$2")

    # Kiểm tra bcrypt hash
    assert bcrypt.checkpw(
        password.encode("utf-8"),
        row["password_hash"].encode("ascii"),
    )

    assert row["created_at"] == row["updated_at"]


def test_register_duplicate_email_rejected(
    test_db: Connection,
) -> None:
    """Không cho đăng ký email trùng, kể cả viết hoa."""

    service = _make_service(test_db)
    email = _unique_email()

    # Đăng ký lần đầu
    service.register(
        email=email,
        password="MatKhau123!",
        confirm_password="MatKhau123!",
        full_name="Nguyễn Văn A",
        phone="0912345678",
    )

    # Đăng ký lại email viết hoa
    with pytest.raises(AppError) as caught:
        service.register(
            email=email.upper(),
            password="MatKhau456!",
            confirm_password="MatKhau456!",
            full_name="Nguyễn Văn B",
            phone="0987654321",
        )

    assert caught.value.error_code == "EMAIL_EXISTS"

    # Database chỉ được có một tài khoản
    count = test_db.execute(
        text("""
            SELECT COUNT(*)
            FROM users
            WHERE email = :email
        """),
        {"email": email},
    ).scalar_one()

    assert count == 1


@pytest.mark.parametrize(
    (
        "email",
        "full_name",
        "phone",
        "password",
        "invalid_field",
    ),
    [
        (
            "email-khong-hop-le",
            "Nguyễn Văn A",
            "0912345678",
            "MatKhau123!",
            "email",
        ),
        (
            "test@example.com",
            "   ",
            "0912345678",
            "MatKhau123!",
            "full_name",
        ),
        (
            "test@example.com",
            "Nguyễn Văn A",
            "123456789",
            "MatKhau123!",
            "phone",
        ),
        (
            "test@example.com",
            "Nguyễn Văn A",
            "0912345678",
            "Abc123",
            "password",
        ),
        (
            "test@example.com",
            "Nguyễn Văn A",
            "0912345678",
            "abcdefgh",
            "password",
        ),
        (
            "test@example.com",
            "Nguyễn Văn A",
            "0912345678",
            "Abcdefg1" * 10,
            "password",
        ),
        (
            "test@example.com",
            "Nguyễn Văn A",
            "0912345678",
            "A1" + "é" * 36,
            "password",
        ),
    ],
)
def test_register_rejects_invalid_input(
    test_db: Connection,
    email: str,
    full_name: str,
    phone: str,
    password: str,
    invalid_field: str,
) -> None:
    """Dữ liệu không hợp lệ phải bị từ chối."""

    service = _make_service(test_db)

    with pytest.raises(AppError) as caught:
        service.register(
            email=email,
            password=password,
            confirm_password=password,
            full_name=full_name,
            phone=phone,
        )

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert invalid_field in caught.value.errors


@pytest.mark.parametrize(
    "wrong_confirmation",
    [
        "KhacMatKhau123!",
        "",
    ],
)
def test_register_confirmation_mismatch_rejected(
    test_db: Connection,
    wrong_confirmation: str,
) -> None:
    """Không được tạo tài khoản nếu xác nhận sai."""

    service = _make_service(test_db)
    email = _unique_email()

    with pytest.raises(AppError) as caught:
        service.register(
            email=email,
            password="MatKhau123!",
            confirm_password=wrong_confirmation,
            full_name="Nguyễn Văn A",
            phone="0912345678",
        )

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert "confirm_password" in caught.value.errors

    # Xác nhận chưa có tài khoản nào được tạo
    count = test_db.execute(
        text("""
            SELECT COUNT(*)
            FROM users
            WHERE email = :email
        """),
        {"email": email},
    ).scalar_one()

    assert count == 0
