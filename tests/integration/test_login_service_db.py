
"""US02 Task 13 - Integration Test đăng nhập trên MariaDB.

Sử dụng Fixture test_db, chỉ kết nối phone_shop_test.
"""

from secrets import token_hex

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from models.app_error import AppError
from services.auth_service import AuthService
from services.auth_session import AUTH_SESSION_USER_ID_KEY

PASSWORD = "MatKhau123!"


class MemorySessionStore:
    """Giả lập lưu session phía server."""

    def __init__(self):
        self.data = {}

    def set(self, key, value):
        self.data[key] = value

    def get(self, key):
        return self.data.get(key)


def _email() -> str:
    """Tạo email riêng cho từng bài kiểm thử."""

    return f"task13_{token_hex(6)}@example.test"


def _service(connection: Connection) -> AuthService:
    """Tạo AuthService dùng kết nối database kiểm thử."""

    def session_factory() -> Session:
        return Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
        )

    return AuthService(
        session_factory=session_factory,
    )


def _create_customer(
    service: AuthService,
    email: str,
):
    """Tạo Customer hợp lệ bằng nghiệp vụ đăng ký thật."""

    return service.register(
        email=email,
        password=PASSWORD,
        confirm_password=PASSWORD,
        full_name="Nguyễn Văn A",
        phone="0912345678",
    )


def test_login_success_with_real_bcrypt_and_session(
    test_db: Connection,
) -> None:
    """Đăng ký rồi đăng nhập qua MariaDB thật."""

    service = _service(test_db)
    email = _email()

    registered = _create_customer(service, email)

    store = MemorySessionStore()

    result = service.login(
        email=f"  {email.upper()}  ",
        password=PASSWORD,
        session_store=store,
    )

    assert result.user_id == registered.user_id
    assert result.email == email
    assert result.role == "CUSTOMER"

    assert store.data == {
        AUTH_SESSION_USER_ID_KEY: registered.user_id,
    }


def test_wrong_password_does_not_create_session(
    test_db: Connection,
) -> None:
    """Sai mật khẩu trên DB thật phải trả lỗi chung."""

    service = _service(test_db)
    email = _email()

    _create_customer(service, email)

    store = MemorySessionStore()

    with pytest.raises(AppError) as caught:
        service.login(
            email=email,
            password="SaiMatKhau123!",
            session_store=store,
        )

    assert caught.value.error_code == "INVALID_CREDENTIALS"
    assert store.data == {}


def test_unknown_email_does_not_create_session(
    test_db: Connection,
) -> None:
    """Email không tồn tại không được xác thực."""

    service = _service(test_db)
    store = MemorySessionStore()

    with pytest.raises(AppError) as caught:
        service.login(
            email=_email(),
            password=PASSWORD,
            session_store=store,
        )

    assert caught.value.error_code == "INVALID_CREDENTIALS"
    assert store.data == {}


def test_locked_account_is_rejected(
    test_db: Connection,
) -> None:
    """Tài khoản LOCKED, mật khẩu đúng vẫn không đăng nhập."""

    service = _service(test_db)
    email = _email()

    registered = _create_customer(service, email)

    # Mô phỏng Admin đã khóa tài khoản.
    # Chỉ UPDATE dữ liệu thử trên phone_shop_test.
    test_db.execute(
        text("""
            UPDATE users
            SET
                status = 'LOCKED',
                lock_reason = 'Integration test'
            WHERE id = :user_id
        """),
        {"user_id": registered.user_id},
    )

    store = MemorySessionStore()

    with pytest.raises(AppError) as caught:
        service.login(
            email=email,
            password=PASSWORD,
            session_store=store,
        )

    assert caught.value.error_code == "ACCOUNT_LOCKED"
    assert store.data == {}


def test_locked_account_wrong_password_is_generic(
    test_db: Connection,
) -> None:
    """Sai mật khẩu không làm lộ việc tài khoản bị khóa."""

    service = _service(test_db)
    email = _email()

    registered = _create_customer(service, email)

    test_db.execute(
        text("""
            UPDATE users
            SET
                status = 'LOCKED',
                lock_reason = 'Integration test'
            WHERE id = :user_id
        """),
        {"user_id": registered.user_id},
    )

    store = MemorySessionStore()

    with pytest.raises(AppError) as caught:
        service.login(
            email=email,
            password="SaiMatKhau123!",
            session_store=store,
        )

    assert caught.value.error_code == "INVALID_CREDENTIALS"
    assert store.data == {}


def test_login_returns_role_from_database(
    test_db: Connection,
) -> None:
    """LoginResult lấy role từ MariaDB, không phải từ client."""

    service = _service(test_db)
    email = _email()

    registered = _create_customer(service, email)

    # Thay role trong DB test để mô phỏng tài khoản Admin.
    test_db.execute(
        text("""
            UPDATE users
            SET role = 'ADMIN'
            WHERE id = :user_id
        """),
        {"user_id": registered.user_id},
    )

    store = MemorySessionStore()

    result = service.login(
        email=email,
        password=PASSWORD,
        session_store=store,
    )

    assert result.role == "ADMIN"

    # Session vẫn chỉ lưu user_id
    assert store.data == {
        AUTH_SESSION_USER_ID_KEY: registered.user_id,
    }


def test_two_sessions_have_independent_user_ids(
    test_db: Connection,
) -> None:
    """Hai session riêng không dùng chung danh tính."""

    service = _service(test_db)

    first = _create_customer(service, _email())
    second = _create_customer(service, _email())

    first_email = first.email
    second_email = second.email

    first_store = MemorySessionStore()
    second_store = MemorySessionStore()

    first_result = service.login(
        email=first_email,
        password=PASSWORD,
        session_store=first_store,
    )

    # Trước khi session thứ hai đăng nhập,
    # nó không có user_id.
    assert second_store.data == {}

    second_result = service.login(
        email=second_email,
        password=PASSWORD,
        session_store=second_store,
    )

    assert first_result.user_id != second_result.user_id

    assert first_store.get(
        AUTH_SESSION_USER_ID_KEY
    ) == first.user_id

    assert second_store.get(
        AUTH_SESSION_USER_ID_KEY
    ) == second.user_id

    assert first_store.data != second_store.data
