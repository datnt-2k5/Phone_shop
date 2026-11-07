
"""US02 Task 13 - Unit Test cho AuthService.login.

Không kết nối MariaDB và không khởi chạy Flet.
"""

from dataclasses import asdict

import bcrypt
import pytest

import services.auth_service as auth_module
from models.app_error import AppError
from services.auth_service import AuthService
from services.auth_session import AUTH_SESSION_USER_ID_KEY

PASSWORD = "MatKhau123!"


class FakeSession:
    """SQLAlchemy Session giả lập cho Unit Test."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class MemorySessionStore:
    """Session Store giả lập bằng dictionary."""

    def __init__(self):
        self.data = {}

    def set(self, key, value):
        self.data[key] = value

    def get(self, key):
        return self.data.get(key)


@pytest.fixture(scope="module")
def password_hash():
    """Hash một lần để dùng lại trong các Unit Test."""

    return bcrypt.hashpw(
        PASSWORD.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("ascii")


def _account(
    password_hash,
    *,
    status="ACTIVE",
    role="CUSTOMER",
):
    """Một bản ghi users giả lập."""

    return {
        "id": 42,
        "email": "unit@example.test",
        "password_hash": password_hash,
        "full_name": "Nguyễn Văn A",
        "phone": "0912345678",
        "role": role,
        "status": status,
    }


def _make_service(monkeypatch, account):
    """Thay UserRepository thật bằng Repository giả lập."""

    class FakeUserRepository:
        def __init__(self, session):
            assert isinstance(session, FakeSession)

        def get_by_email(self, email):
            if account is None:
                return None

            if email == account["email"]:
                return account

            return None

    monkeypatch.setattr(
        auth_module,
        "UserRepository",
        FakeUserRepository,
    )

    return AuthService(
        session_factory=FakeSession,
    )


def test_login_success_stores_only_user_id(
    monkeypatch,
    password_hash,
):
    """Đăng nhập thành công chỉ lưu user_id vào session."""

    service = _make_service(
        monkeypatch,
        _account(password_hash),
    )
    store = MemorySessionStore()

    result = service.login(
        email="  UNIT@EXAMPLE.TEST  ",
        password=PASSWORD,
        session_store=store,
    )

    assert result.user_id == 42
    assert result.email == "unit@example.test"
    assert result.full_name == "Nguyễn Văn A"
    assert result.role == "CUSTOMER"

    assert store.get(AUTH_SESSION_USER_ID_KEY) == 42

    # Không lưu password, hash, email, role trong session
    assert store.data == {
        AUTH_SESSION_USER_ID_KEY: 42,
    }

    # Kết quả trả về không chứa bí mật
    result_data = asdict(result)
    assert "password" not in result_data
    assert "password_hash" not in result_data


def test_login_wrong_password_rejected(
    monkeypatch,
    password_hash,
):
    """Sai mật khẩu: không tạo session."""

    service = _make_service(
        monkeypatch,
        _account(password_hash),
    )
    store = MemorySessionStore()

    with pytest.raises(AppError) as caught:
        service.login(
            email="unit@example.test",
            password="SaiMatKhau123!",
            session_store=store,
        )

    assert caught.value.error_code == "INVALID_CREDENTIALS"
    assert store.data == {}


def test_login_unknown_email_rejected(
    monkeypatch,
    password_hash,
):
    """Email chưa tồn tại: lỗi chung, không tạo session."""

    service = _make_service(
        monkeypatch,
        _account(password_hash),
    )
    store = MemorySessionStore()

    with pytest.raises(AppError) as caught:
        service.login(
            email="unknown@example.test",
            password=PASSWORD,
            session_store=store,
        )

    assert caught.value.error_code == "INVALID_CREDENTIALS"
    assert store.data == {}


def test_locked_account_cannot_login(
    monkeypatch,
    password_hash,
):
    """Mật khẩu đúng nhưng tài khoản LOCKED phải bị chặn."""

    service = _make_service(
        monkeypatch,
        _account(
            password_hash,
            status="LOCKED",
        ),
    )
    store = MemorySessionStore()

    with pytest.raises(AppError) as caught:
        service.login(
            email="unit@example.test",
            password=PASSWORD,
            session_store=store,
        )

    assert caught.value.error_code == "ACCOUNT_LOCKED"
    assert store.data == {}


def test_locked_account_wrong_password_is_generic(
    monkeypatch,
    password_hash,
):
    """Tài khoản LOCKED nhưng mật khẩu sai không lộ trạng thái."""

    service = _make_service(
        monkeypatch,
        _account(
            password_hash,
            status="LOCKED",
        ),
    )
    store = MemorySessionStore()

    with pytest.raises(AppError) as caught:
        service.login(
            email="unit@example.test",
            password="SaiMatKhau123!",
            session_store=store,
        )

    assert caught.value.error_code == "INVALID_CREDENTIALS"
    assert store.data == {}


@pytest.mark.parametrize(
    ("email", "password"),
    [
        (None, PASSWORD),
        ("", PASSWORD),
        ("khong-phai-email", PASSWORD),
        ("a" * 101 + "@example.test", PASSWORD),
        ("unit@example.test", None),
        ("unit@example.test", ""),
        ("unit@example.test", "A1" + "é" * 36),
    ],
)
def test_login_rejects_invalid_input(
    monkeypatch,
    password_hash,
    email,
    password,
):
    """Dữ liệu không hợp lệ không được tạo session."""

    service = _make_service(
        monkeypatch,
        _account(password_hash),
    )
    store = MemorySessionStore()

    with pytest.raises(AppError) as caught:
        service.login(
            email=email,
            password=password,
            session_store=store,
        )

    assert caught.value.error_code == "INVALID_CREDENTIALS"
    assert store.data == {}


def test_login_role_comes_from_database(
    monkeypatch,
    password_hash,
):
    """Role trả về phải đến từ tài khoản đã xác thực."""

    service = _make_service(
        monkeypatch,
        _account(
            password_hash,
            role="ADMIN",
        ),
    )
    store = MemorySessionStore()

    result = service.login(
        email="unit@example.test",
        password=PASSWORD,
        session_store=store,
    )

    assert result.role == "ADMIN"

    # Session chỉ lưu ID, không lưu role
    assert store.data == {
        AUTH_SESSION_USER_ID_KEY: 42,
    }


def test_login_does_not_claim_success_when_session_fails(
    monkeypatch,
    password_hash,
):
    """Không trả thành công nếu không thể lưu server session."""

    service = _make_service(
        monkeypatch,
        _account(password_hash),
    )

    class BrokenSessionStore:
        def set(self, key, value):
            raise RuntimeError("Session storage unavailable")

    with pytest.raises(RuntimeError):
        service.login(
            email="unit@example.test",
            password=PASSWORD,
            session_store=BrokenSessionStore(),
        )
