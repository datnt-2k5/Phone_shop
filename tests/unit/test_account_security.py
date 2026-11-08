
"""US03 Task 20 - Unit Test cho password va avatar.

Khong ket noi MariaDB; su dung Repository gia lap.
"""

from contextlib import nullcontext
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import bcrypt
import pytest
from PIL import Image

import services.account_security_service as security_module
from models.app_error import AppError
from services.account_security_service import (
    MAX_AVATAR_BYTES,
    AccountSecurityService,
    prepare_avatar,
)
from services.auth_session import AUTH_SESSION_USER_ID_KEY

OLD_PASSWORD = "MatKhau123!"
NEW_PASSWORD = "MatKhauMoi456!"


class StrictSessionStore:
    def __init__(self, user_id=7):
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
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def begin(self):
        return nullcontext()


def make_image(image_format: str) -> bytes:
    """Tao anh nho hop le bang Pillow."""

    output = BytesIO()
    image = Image.new(
        "RGB",
        (32, 32),
        color=(40, 120, 200),
    )
    image.save(output, format=image_format)
    return output.getvalue()


@pytest.fixture
def fake_security(monkeypatch, tmp_path: Path):
    """Service va Repository gia lap de test nhanh."""

    data = {
        "id": 7,
        "status": "ACTIVE",
        "password_hash": bcrypt.hashpw(
            OLD_PASSWORD.encode("utf-8"),
            bcrypt.gensalt(),
        ).decode("ascii"),
        "avatar_url": None,
        "updated_by": None,
    }

    class FakeRepository:
        def __init__(self, session):
            assert isinstance(session, FakeSession)

        def get_security_by_id(self, user_id, *, for_update=False):
            if user_id != data["id"]:
                return None
            return dict(data)

        def update_password_hash(
            self,
            *,
            user_id,
            password_hash,
            now_utc,
        ):
            assert user_id == data["id"]
            data["password_hash"] = password_hash
            data["updated_by"] = user_id

        def get_by_id(self, user_id, *, for_update=False):
            if user_id != data["id"]:
                return None
            return dict(data)

        def update_avatar_url(
            self,
            *,
            user_id,
            avatar_url,
            now_utc,
        ):
            assert user_id == data["id"]
            data["avatar_url"] = avatar_url
            data["updated_by"] = user_id

    monkeypatch.setattr(
        security_module,
        "UserRepository",
        FakeRepository,
    )

    service = AccountSecurityService(
        session_factory=FakeSession,
        avatar_dir=tmp_path / "avatars",
    )

    # Unit Test nay tap trung vao nghiep vu; Auth guard
    # da co cac Integration Test rieng o Task 14-19.
    service.auth_service.require_user = (
        lambda *, session_store:
        SimpleNamespace(user_id=7)
    )

    return service, data, StrictSessionStore()


def test_change_password_success_and_logout(fake_security):
    service, data, store = fake_security
    old_hash = data["password_hash"]

    service.change_password(
        session_store=store,
        old_password=OLD_PASSWORD,
        new_password=NEW_PASSWORD,
        confirm_new_password=NEW_PASSWORD,
    )

    assert data["password_hash"] != old_hash
    assert bcrypt.checkpw(
        NEW_PASSWORD.encode(),
        data["password_hash"].encode(),
    )
    assert data["updated_by"] == 7
    assert store.get(AUTH_SESSION_USER_ID_KEY) is None


def test_wrong_old_password_does_not_change_hash(fake_security):
    service, data, store = fake_security
    before = data["password_hash"]

    with pytest.raises(AppError) as caught:
        service.change_password(
            session_store=store,
            old_password="SaiMatKhau123!",
            new_password=NEW_PASSWORD,
            confirm_new_password=NEW_PASSWORD,
        )

    assert caught.value.error_code == "INVALID_OLD_PASSWORD"
    assert data["password_hash"] == before
    assert store.get(AUTH_SESSION_USER_ID_KEY) == 7


def test_reusing_old_password_is_rejected(fake_security):
    service, data, store = fake_security
    before = data["password_hash"]

    with pytest.raises(AppError) as caught:
        service.change_password(
            session_store=store,
            old_password=OLD_PASSWORD,
            new_password=OLD_PASSWORD,
            confirm_new_password=OLD_PASSWORD,
        )

    assert caught.value.error_code == "PASSWORD_REUSED"
    assert data["password_hash"] == before


@pytest.mark.parametrize(
    "new_password",
    [
        "abc123",
        "abcdefgh",
        "A1" + "é" * 36,
    ],
)
def test_invalid_new_password_is_rejected(
    fake_security,
    new_password,
):
    service, data, store = fake_security
    before = data["password_hash"]

    with pytest.raises(AppError):
        service.change_password(
            session_store=store,
            old_password=OLD_PASSWORD,
            new_password=new_password,
            confirm_new_password=new_password,
        )

    assert data["password_hash"] == before
    assert store.get(AUTH_SESSION_USER_ID_KEY) == 7


def test_password_confirmation_must_match(fake_security):
    service, data, store = fake_security
    before = data["password_hash"]

    with pytest.raises(AppError) as caught:
        service.change_password(
            session_store=store,
            old_password=OLD_PASSWORD,
            new_password=NEW_PASSWORD,
            confirm_new_password="KhacMatKhau789!",
        )

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert data["password_hash"] == before


@pytest.mark.parametrize(
    ("image_format", "extension"),
    [
        ("JPEG", ".jpg"),
        ("PNG", ".png"),
    ],
)
def test_prepare_valid_image(image_format, extension):
    cleaned, actual_extension = prepare_avatar(
        make_image(image_format)
    )

    assert actual_extension == extension
    assert len(cleaned) <= MAX_AVATAR_BYTES

    with Image.open(BytesIO(cleaned)) as image:
        assert image.format == image_format
        assert image.size == (32, 32)


@pytest.mark.parametrize(
    "bad_data",
    [
        b"",
        b"not-an-image",
        b"\x89PNG\r\n\x1a\nbroken-image",
        b"A" * (MAX_AVATAR_BYTES + 1),
    ],
)
def test_prepare_invalid_image_is_rejected(bad_data):
    with pytest.raises(AppError) as caught:
        prepare_avatar(bad_data)

    assert caught.value.error_code in {
        "INVALID_AVATAR",
        "AVATAR_TOO_LARGE",
    }


def test_gif_is_rejected():
    with pytest.raises(AppError) as caught:
        prepare_avatar(make_image("GIF"))

    assert caught.value.error_code == "INVALID_AVATAR"


def test_avatar_upload_uses_uuid_filename(fake_security):
    service, data, store = fake_security

    result = service.upload_avatar(
        session_store=store,
        image_bytes=make_image("PNG"),
    )

    filename = Path(result.avatar_url).name

    assert result.user_id == 7
    assert result.avatar_url.startswith("avatars/")
    assert filename.endswith(".png")
    assert len(filename.split(".")[0]) == 32
    assert data["avatar_url"] == result.avatar_url
    assert data["updated_by"] == 7

    assert (service.avatar_dir / filename).is_file()
    assert store.get(AUTH_SESSION_USER_ID_KEY) == 7


def test_locked_account_cannot_change_password(fake_security):
    service, data, store = fake_security
    data["status"] = "LOCKED"

    with pytest.raises(AppError):
        service.change_password(
            session_store=store,
            old_password=OLD_PASSWORD,
            new_password=NEW_PASSWORD,
            confirm_new_password=NEW_PASSWORD,
        )


def test_locked_account_cannot_upload_avatar(fake_security):
    service, data, store = fake_security
    data["status"] = "LOCKED"

    with pytest.raises(AppError):
        service.upload_avatar(
            session_store=store,
            image_bytes=make_image("JPEG"),
        )

    assert data["avatar_url"] is None
    assert not list(service.avatar_dir.glob("*"))


def test_avatar_database_error_removes_new_file(
    fake_security,
    monkeypatch,
):
    service, data, store = fake_security

    original_repository = security_module.UserRepository

    class FailingRepository(original_repository):
        def update_avatar_url(self, **kwargs):
            raise RuntimeError("Simulated DB failure")

    monkeypatch.setattr(
        security_module,
        "UserRepository",
        FailingRepository,
    )

    with pytest.raises(RuntimeError, match="Simulated DB failure"):
        service.upload_avatar(
            session_store=store,
            image_bytes=make_image("PNG"),
        )

    assert data["avatar_url"] is None
    assert list(service.avatar_dir.glob("*")) == []
