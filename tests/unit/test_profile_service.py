
"""US03 Task 17: Unit Test cho hồ sơ cá nhân.

Không kết nối MariaDB thật.
"""

from contextlib import nullcontext
from datetime import UTC, datetime

import pytest

import services.auth_service as auth_module
import services.profile_service as profile_module
from models.app_error import AppError
from services.auth_session import AUTH_SESSION_USER_ID_KEY
from services.profile_service import ProfileService
from utils.time_utils import FixedClock
from utils.validators import validate_address

FIXED_UTC = datetime(2026, 11, 8, 7, 15)
CREATED_UTC = datetime(2026, 1, 1, 8, 0)


class MemorySessionStore:
    """Mô phỏng Session Store với remove() nghiêm ngặt."""

    def __init__(self, user_id=42):
        self.data = {}
        if user_id is not None:
            self.data[AUTH_SESSION_USER_ID_KEY] = user_id

    def set(self, key, value):
        self.data[key] = value

    def get(self, key):
        return self.data.get(key)

    def remove(self, key):
        self.data.pop(key)


class FakeSession:
    """Session không truy cập database."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def begin(self):
        return nullcontext()


@pytest.fixture
def scenario(monkeypatch):
    """Tạo hai tài khoản giả lập và một ProfileService."""

    rows = {
        42: {
            "id": 42,
            "email": "first@example.test",
            "full_name": "Nguyễn Văn A",
            "phone": "0912345678",
            "address": None,
            "role": "CUSTOMER",
            "status": "ACTIVE",
            "created_at": CREATED_UTC,
            "updated_at": CREATED_UTC,
            "updated_by": None,
        },
        43: {
            "id": 43,
            "email": "second@example.test",
            "full_name": "Nguyễn Văn B",
            "phone": "0987654321",
            "address": "Hà Nội",
            "role": "CUSTOMER",
            "status": "ACTIVE",
            "created_at": CREATED_UTC,
            "updated_at": CREATED_UTC,
            "updated_by": None,
        },
    }

    class FakeUserRepository:
        def __init__(self, session):
            assert isinstance(session, FakeSession)

        def get_by_id(self, user_id, *, for_update=False):
            row = rows.get(user_id)
            return dict(row) if row is not None else None

        def update_own_profile(
            self,
            *,
            user_id,
            full_name,
            phone,
            address,
            now_utc,
        ):
            rows[user_id].update(
                full_name=full_name,
                phone=phone,
                address=address,
                updated_at=now_utc,
                updated_by=user_id,
            )

    # AuthService và ProfileService phải sử dụng
    # cùng dữ liệu Repository giả lập.
    monkeypatch.setattr(
        auth_module,
        "UserRepository",
        FakeUserRepository,
    )
    monkeypatch.setattr(
        profile_module,
        "UserRepository",
        FakeUserRepository,
    )

    service = ProfileService(
        session_factory=FakeSession,
        clock=FixedClock(
            datetime(2026, 11, 8, 7, 15, tzinfo=UTC)
        ),
    )

    return service, rows, MemorySessionStore()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("  Đà Nẵng  ", "Đà Nẵng"),
        ("   ", None),
    ],
)
def test_valid_address(raw, expected):
    assert validate_address(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        123,
        "A" * 256,
    ],
)
def test_invalid_address(raw):
    with pytest.raises(AppError) as caught:
        validate_address(raw)

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert "address" in caught.value.errors


def test_get_my_profile_uses_session_identity(scenario):
    service, _, store = scenario

    result = service.get_my_profile(
        session_store=store,
    )

    assert result.user_id == 42
    assert result.email == "first@example.test"
    assert result.role == "CUSTOMER"
    assert result.status == "ACTIVE"
    assert result.address is None
    assert result.updated_by is None


def test_update_profile_and_audit_fields(scenario):
    service, rows, store = scenario

    result = service.update_my_profile(
        session_store=store,
        full_name="  Nguyễn   Văn   Mới  ",
        phone="  0901234567  ",
        address="  Đà Nẵng  ",
    )

    assert result.user_id == 42
    assert result.full_name == "Nguyễn Văn Mới"
    assert result.phone == "0901234567"
    assert result.address == "Đà Nẵng"
    assert result.updated_at == FIXED_UTC
    assert result.updated_by == 42

    assert rows[42]["email"] == "first@example.test"
    assert rows[42]["role"] == "CUSTOMER"
    assert rows[42]["status"] == "ACTIVE"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("email", "hacker@example.test"),
        ("role", "SUPER_ADMIN"),
        ("status", "ACTIVE"),
        ("user_id", 43),
    ],
)
def test_cannot_pass_protected_fields(
    scenario,
    field,
    value,
):
    service, rows, store = scenario
    original = dict(rows[42])

    kwargs = {
        "full_name": "Nguyễn Văn A",
        "phone": "0912345678",
        "address": None,
        field: value,
    }

    with pytest.raises(TypeError):
        service.update_my_profile(
            session_store=store,
            **kwargs,
        )

    assert rows[42] == original


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("full_name", "   "),
        ("phone", "12345"),
        ("address", "A" * 256),
    ],
)
def test_invalid_update_does_not_change_data(
    scenario,
    field,
    value,
):
    service, rows, store = scenario
    original = dict(rows[42])

    kwargs = {
        "full_name": "Nguyễn Văn A",
        "phone": "0912345678",
        "address": None,
    }
    kwargs[field] = value

    with pytest.raises(AppError) as caught:
        service.update_my_profile(
            session_store=store,
            **kwargs,
        )

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert field in caught.value.errors
    assert rows[42] == original


@pytest.mark.parametrize("action", ["read", "update"])
def test_missing_session_is_unauthorized(
    scenario,
    action,
):
    service, rows, _ = scenario
    store = MemorySessionStore(user_id=None)
    original = dict(rows[42])

    with pytest.raises(AppError) as caught:
        if action == "read":
            service.get_my_profile(session_store=store)
        else:
            service.update_my_profile(
                session_store=store,
                full_name="Nguyễn Văn Mới",
                phone="0901234567",
                address="Đà Nẵng",
            )

    assert caught.value.error_code == "UNAUTHORIZED"
    assert rows[42] == original


def test_update_does_not_change_another_user(scenario):
    service, rows, store = scenario
    other_before = dict(rows[43])

    service.update_my_profile(
        session_store=store,
        full_name="Nguyễn Văn Mới",
        phone="0901234567",
        address="Đà Nẵng",
    )

    assert rows[43] == other_before


def test_locked_account_cannot_update(scenario):
    service, rows, store = scenario
    rows[42]["status"] = "LOCKED"

    with pytest.raises(AppError) as caught:
        service.update_my_profile(
            session_store=store,
            full_name="Tên mới",
            phone="0901234567",
            address=None,
        )

    assert caught.value.error_code == "ACCOUNT_LOCKED"
    assert store.get(AUTH_SESSION_USER_ID_KEY) is None
    assert rows[42]["full_name"] == "Nguyễn Văn A"


def test_repeated_update_keeps_valid_profile(scenario):
    service, _, store = scenario

    for _ in range(2):
        result = service.update_my_profile(
            session_store=store,
            full_name="Nguyễn Văn A",
            phone="0912345678",
            address=None,
        )

    assert result.updated_by == 42
    assert result.updated_at == FIXED_UTC
