
"""US02 Task 14 - Unit Test require_user và logout.

Không truy vấn MariaDB thật.
"""

import pytest

import services.auth_service as auth_module
from models.app_error import AppError
from services.auth_service import AuthService
from services.auth_session import (
    AUTH_SESSION_USER_ID_KEY,
    CART_SESSION_KEY,
    CHECKOUT_SESSION_KEY,
    USER_CACHE_SESSION_KEY,
)


class MemorySessionStore:
    """Giả lập Flet server-side Session Store."""

    def __init__(self):
        self.data = {}

    def set(self, key, value):
        self.data[key] = value

    def get(self, key):
        return self.data.get(key)

    def remove(self, key):
        self.data.pop(key, None)


class FakeDatabaseSession:
    """Session giả lập, không mở kết nối MariaDB."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


def _user(
    *,
    status="ACTIVE",
    role="CUSTOMER",
):
    """Tài khoản giả lập để kiểm tra Session Guard."""

    return {
        "id": 42,
        "email": "customer@example.test",
        "full_name": "Nguyễn Văn A",
        "phone": "0912345678",
        "role": role,
        "status": status,
    }


def _service(monkeypatch, account):
    """Thay UserRepository bằng Repository giả lập."""

    class FakeUserRepository:
        def __init__(self, session):
            assert isinstance(session, FakeDatabaseSession)

        def get_by_id(self, user_id):
            if account is None:
                return None

            if user_id == account["id"]:
                return dict(account)

            return None

    monkeypatch.setattr(
        auth_module,
        "UserRepository",
        FakeUserRepository,
    )

    return AuthService(
        session_factory=FakeDatabaseSession,
    )


def _logged_in_store():
    """Session với user_id đã được xác thực."""

    store = MemorySessionStore()
    store.set(AUTH_SESSION_USER_ID_KEY, 42)
    return store


def _fill_private_state(store):
    """Thêm dữ liệu sẽ phải xóa khi logout."""

    store.set(CART_SESSION_KEY, [{"product_id": 1}])
    store.set(CHECKOUT_SESSION_KEY, "checkout-demo-key")
    store.set(USER_CACHE_SESSION_KEY, {"full_name": "Test"})


def test_require_user_reads_active_account(
    monkeypatch,
):
    """User ACTIVE được tải lại từ database."""

    service = _service(monkeypatch, _user())
    store = _logged_in_store()

    result = service.require_user(
        session_store=store,
        allowed_roles={"CUSTOMER"},
    )

    assert result.user_id == 42
    assert result.email == "customer@example.test"
    assert result.role == "CUSTOMER"
    assert result.status == "ACTIVE"

    assert store.get(AUTH_SESSION_USER_ID_KEY) == 42


def test_missing_session_is_unauthorized(
    monkeypatch,
):
    """Chưa đăng nhập không được truy cập nghiệp vụ."""

    service = _service(monkeypatch, _user())
    store = MemorySessionStore()

    # Giỏ của khách chưa đăng nhập không bị tự động xóa.
    store.set(CART_SESSION_KEY, [{"product_id": 1}])

    with pytest.raises(AppError) as caught:
        service.require_user(session_store=store)

    assert caught.value.error_code == "UNAUTHORIZED"
    assert store.get(CART_SESSION_KEY) == [
        {"product_id": 1}
    ]


@pytest.mark.parametrize(
    "invalid_id",
    [
        False,
        True,
        0,
        -1,
        "42",
        42.0,
    ],
)
def test_invalid_session_id_is_rejected(
    monkeypatch,
    invalid_id,
):
    """Bool, số âm, chuỗi và float không phải ID hợp lệ."""

    service = _service(monkeypatch, _user())
    store = MemorySessionStore()

    store.set(AUTH_SESSION_USER_ID_KEY, invalid_id)
    _fill_private_state(store)

    with pytest.raises(AppError) as caught:
        service.require_user(session_store=store)

    assert caught.value.error_code == "UNAUTHORIZED"

    assert store.get(AUTH_SESSION_USER_ID_KEY) is None
    assert store.get(CART_SESSION_KEY) is None
    assert store.get(CHECKOUT_SESSION_KEY) is None
    assert store.get(USER_CACHE_SESSION_KEY) is None


def test_deleted_user_invalidates_session(
    monkeypatch,
):
    """User không còn trong DB phải mất phiên đăng nhập."""

    service = _service(monkeypatch, None)
    store = _logged_in_store()
    _fill_private_state(store)

    with pytest.raises(AppError) as caught:
        service.require_user(session_store=store)

    assert caught.value.error_code == "UNAUTHORIZED"
    assert store.data == {}


def test_locked_user_invalidates_session(
    monkeypatch,
):
    """Tài khoản LOCKED bị chặn dù session còn user_id."""

    service = _service(
        monkeypatch,
        _user(status="LOCKED"),
    )
    store = _logged_in_store()
    _fill_private_state(store)

    with pytest.raises(AppError) as caught:
        service.require_user(session_store=store)

    assert caught.value.error_code == "ACCOUNT_LOCKED"
    assert store.data == {}


def test_wrong_role_returns_forbidden(
    monkeypatch,
):
    """Customer không được thực hiện thao tác chỉ dành cho Admin."""

    service = _service(monkeypatch, _user())
    store = _logged_in_store()

    with pytest.raises(AppError) as caught:
        service.require_user(
            session_store=store,
            allowed_roles={"ADMIN", "SUPER_ADMIN"},
        )

    assert caught.value.error_code == "FORBIDDEN"

    # Không đủ role không có nghĩa là mất đăng nhập.
    assert store.get(AUTH_SESSION_USER_ID_KEY) == 42


def test_role_change_is_checked_again(
    monkeypatch,
):
    """Role thay đổi trong DB phải có hiệu lực ngay lần kiểm tra sau."""

    account = _user(role="ADMIN")
    service = _service(monkeypatch, account)
    store = _logged_in_store()

    first = service.require_user(
        session_store=store,
        allowed_roles={"ADMIN"},
    )

    assert first.role == "ADMIN"

    # Giả lập Super Admin hạ quyền trong MariaDB.
    account["role"] = "CUSTOMER"

    with pytest.raises(AppError) as caught:
        service.require_user(
            session_store=store,
            allowed_roles={"ADMIN"},
        )

    assert caught.value.error_code == "FORBIDDEN"

    current = service.require_user(
        session_store=store,
        allowed_roles={"CUSTOMER"},
    )

    assert current.role == "CUSTOMER"


def test_logout_clears_private_session_keys():
    """Logout xóa đúng bốn khóa trạng thái người dùng."""

    store = _logged_in_store()
    _fill_private_state(store)

    # Trạng thái giao diện độc lập cần được giữ lại.
    store.set("phone_shop.ui.theme", "dark")

    AuthService.logout(session_store=store)

    assert store.get(AUTH_SESSION_USER_ID_KEY) is None
    assert store.get(CART_SESSION_KEY) is None
    assert store.get(CHECKOUT_SESSION_KEY) is None
    assert store.get(USER_CACHE_SESSION_KEY) is None

    assert store.data == {
        "phone_shop.ui.theme": "dark",
    }


def test_logout_is_idempotent():
    """Đăng xuất hai lần liên tiếp không phát sinh lỗi."""

    store = _logged_in_store()
    _fill_private_state(store)

    AuthService.logout(session_store=store)
    AuthService.logout(session_store=store)

    assert store.data == {}


def test_cached_role_cannot_override_database_role(
    monkeypatch,
):
    """Không tin role được lưu trong cache session."""

    service = _service(
        monkeypatch,
        _user(role="CUSTOMER"),
    )
    store = _logged_in_store()

    # Cache cũ hoặc giả lập ghi rằng người dùng là Admin.
    store.set(USER_CACHE_SESSION_KEY, {"role": "ADMIN"})

    with pytest.raises(AppError) as caught:
        service.require_user(
            session_store=store,
            allowed_roles={"ADMIN"},
        )

    assert caught.value.error_code == "FORBIDDEN"
    assert store.get(AUTH_SESSION_USER_ID_KEY) == 42


def test_logout_with_missing_keys_like_real_flet():
    """Logout không lỗi khi Flet Session thiếu cart/checkout/cache."""

    class StrictFletSessionStore:
        """Mô phỏng hành vi remove() thực tế của Flet."""

        def __init__(self):
            self.data = {
                AUTH_SESSION_USER_ID_KEY: 42,
                "phone_shop.ui.theme": "dark",
            }

        def set(self, key, value):
            self.data[key] = value

        def get(self, key):
            return self.data.get(key)

        def remove(self, key):
            # Giống Flet: không có key thì phát sinh KeyError.
            self.data.pop(key)

    store = StrictFletSessionStore()

    # Ban đầu chỉ có user_id, chưa có giỏ hàng.
    assert store.get(AUTH_SESSION_USER_ID_KEY) == 42

    # Phải đăng xuất thành công, không bị KeyError.
    AuthService.logout(session_store=store)

    assert store.get(AUTH_SESSION_USER_ID_KEY) is None

    # Tùy chọn giao diện vẫn được giữ.
    assert store.data == {
        "phone_shop.ui.theme": "dark",
    }

    # Đăng xuất thêm lần nữa cũng không được phát sinh lỗi.
    AuthService.logout(session_store=store)

    assert store.data == {
        "phone_shop.ui.theme": "dark",
    }
