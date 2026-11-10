
"""Task 32: image byte validation, UUID storage, permission and rollback."""

from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from uuid import UUID

import pytest
from PIL import Image

from models.app_error import AppError
from repositories.product_image_repository import ProductImageRepository
from services.permissions import Permission
from services.product_image_service import (
    MAX_PRODUCT_IMAGE_BYTES,
    ProductImageService,
    prepare_product_image,
)
from utils.time_utils import FixedClock

NOW = datetime(2026, 11, 10, 7, tzinfo=UTC)


def sample_image(fmt="PNG", *, size=(16, 16)):
    output = BytesIO()
    Image.new("RGB", size, (5, 30, 60)).save(
        output,
        format=fmt,
    )
    return output.getvalue()


class FakeAuth:
    def require_user(self, *, session_store):
        return SimpleNamespace(user_id=17)


class FakeGuard:
    def __init__(self):
        self.permissions = []
        self.error = None
        self.after_action_error = None

    def run_allowed(
        self,
        *,
        session_store,
        permission,
        action,
    ):
        self.permissions.append(permission)

        if self.error:
            raise AppError(self.error, "Denied")

        result = action(object())

        if self.after_action_error:
            raise RuntimeError("commit failed")

        return result


class FakeRepo:
    def __init__(self):
        self.row = {
            "id": 9,
            "image_url": "/old.png",
            "stock": 4,
            "cost_price": 100,
        }
        self.update_args = None
        self.raise_on_update = False
        self.missing = False
        self.locked = False

    def get_by_id(
        self,
        product_id,
        *,
        for_update=False,
    ):
        self.locked = for_update
        if self.missing:
            return None
        return self.row if product_id == 9 else None

    def update_image_url(self, **kwargs):
        self.update_args = kwargs

        if self.raise_on_update:
            raise RuntimeError("SQL failed")

        self.row["image_url"] = kwargs["image_url"]
        return True


@pytest.fixture
def env(tmp_path):
    repo = FakeRepo()
    guard = FakeGuard()

    service = ProductImageService(
        image_dir=tmp_path / "products",
        clock=FixedClock(NOW),
        auth_service=FakeAuth(),
        protected_actions=guard,
        repository_factory=lambda session: repo,
    )

    return service, repo, guard, tmp_path / "products"


@pytest.mark.parametrize(
    "fmt,suffix",
    [
        ("JPEG", ".jpg"),
        ("PNG", ".png"),
    ],
)
def test_prepared_real_image_is_decodable(fmt, suffix):
    payload, ext = prepare_product_image(
        sample_image(fmt)
    )

    assert ext == suffix

    with Image.open(BytesIO(payload)) as actual:
        assert actual.format == fmt
        assert actual.size == (16, 16)


@pytest.mark.parametrize(
    "bad",
    [
        b"",
        b"junk",
        b"<script>bad</script>",
        None,
        "image",
    ],
)
def test_invalid_payload_is_rejected(bad):
    with pytest.raises(AppError) as caught:
        prepare_product_image(bad)

    assert (
        caught.value.error_code
        == "INVALID_PRODUCT_IMAGE"
    )


def test_oversized_payload_is_rejected():
    with pytest.raises(AppError) as caught:
        prepare_product_image(
            b"x" * (MAX_PRODUCT_IMAGE_BYTES + 1)
        )

    assert (
        caught.value.error_code
        == "PRODUCT_IMAGE_TOO_LARGE"
    )


def test_gif_is_rejected():
    with pytest.raises(AppError) as caught:
        prepare_product_image(sample_image("GIF"))

    assert (
        caught.value.error_code
        == "INVALID_PRODUCT_IMAGE"
    )


def test_dimensions_are_limited():
    with pytest.raises(AppError) as caught:
        prepare_product_image(
            sample_image(size=(4097, 2))
        )

    assert (
        caught.value.error_code
        == "INVALID_PRODUCT_IMAGE"
    )


def test_upload_creates_uuid_name_and_updates_only_image(env):
    service, repo, guard, target_dir = env

    result = service.upload(
        session_store=object(),
        product_id=9,
        image_bytes=sample_image("PNG"),
    )

    assert guard.permissions == [
        Permission.MANAGE_PRODUCTS
    ]
    assert result.product_id == 9
    assert result.image_url.startswith("/products/")

    file_name = result.image_url.rsplit(
        "/", maxsplit=1
    )[-1]

    assert UUID(file_name[:-4]).version == 4
    assert file_name.endswith(".png")
    assert (target_dir / file_name).is_file()

    assert repo.update_args["updated_by"] == 17
    assert (
        repo.update_args["now_utc"]
        == NOW.replace(tzinfo=None)
    )
    assert repo.locked is True
    assert repo.row["stock"] == 4
    assert repo.row["cost_price"] == 100


def test_upload_does_not_trust_client_file_name(env):
    service, _, _, _ = env

    with pytest.raises(TypeError):
        service.upload(
            session_store=object(),
            product_id=9,
            image_bytes=sample_image(),
            file_name="../unsafe.php",
        )


@pytest.mark.parametrize(
    "error_code",
    [
        "FORBIDDEN",
        "ACCOUNT_LOCKED",
        "UNAUTHORIZED",
    ],
)
def test_denied_account_writes_no_file(env, error_code):
    service, repo, guard, target_dir = env
    guard.error = error_code

    with pytest.raises(AppError) as caught:
        service.upload(
            session_store=object(),
            product_id=9,
            image_bytes=sample_image(),
        )

    assert caught.value.error_code == error_code
    assert not target_dir.exists()
    assert repo.update_args is None


@pytest.mark.parametrize(
    "bad_id",
    [0, -1, True, "9"],
)
def test_invalid_product_id_fails_without_file(env, bad_id):
    service, _, _, target_dir = env

    with pytest.raises(AppError) as caught:
        service.upload(
            session_store=object(),
            product_id=bad_id,
            image_bytes=sample_image(),
        )

    assert (
        caught.value.error_code
        == "VALIDATION_ERROR"
    )
    assert not target_dir.exists()


def test_missing_product_does_not_save_file(env):
    service, repo, _, target_dir = env
    repo.missing = True

    with pytest.raises(AppError) as caught:
        service.upload(
            session_store=object(),
            product_id=9,
            image_bytes=sample_image(),
        )

    assert caught.value.error_code == "NOT_FOUND"
    assert not target_dir.exists()


def test_sql_error_cleans_created_file(env):
    service, repo, _, target_dir = env
    repo.raise_on_update = True

    with pytest.raises(
        RuntimeError,
        match="SQL failed",
    ):
        service.upload(
            session_store=object(),
            product_id=9,
            image_bytes=sample_image(),
        )

    assert list(target_dir.iterdir()) == []


def test_commit_error_cleans_created_file(env):
    service, _, guard, target_dir = env
    guard.after_action_error = True

    with pytest.raises(
        RuntimeError,
        match="commit failed",
    ):
        service.upload(
            session_store=object(),
            product_id=9,
            image_bytes=sample_image(),
        )

    assert list(target_dir.iterdir()) == []


def test_invalid_bytes_never_create_directory(env):
    service, _, _, target_dir = env

    with pytest.raises(AppError):
        service.upload(
            session_store=object(),
            product_id=9,
            image_bytes=b"invalid",
        )

    assert not target_dir.exists()


class SqlResult:
    rowcount = 1


class SqlSession:
    def __init__(self):
        self.statement = None
        self.params = None

    def execute(self, statement, params):
        self.statement = statement.text
        self.params = params
        return SqlResult()


def test_repository_updates_only_image_and_audit():
    session = SqlSession()
    repo = ProductImageRepository(session)

    assert repo.update_image_url(
        product_id=9,
        image_url="/products/a.jpg",
        now_utc=NOW.replace(tzinfo=None),
        updated_by=17,
    )

    sql = session.statement.split(
        "SET",
        maxsplit=1,
    )[1].split(
        "WHERE",
        maxsplit=1,
    )[0]

    assert "image_url =" in sql
    assert "stock =" not in sql
    assert "cost_price =" not in sql
    assert session.params["product_id"] == 9
