
"""US05-T09: authenticated product image upload, JPG/PNG, UUID file name."""

import os
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.orm import Session

from database.connection import SessionLocal
from models.app_error import AppError
from repositories.product_image_repository import ProductImageRepository
from services.auth_service import AuthService
from services.auth_session import AuthSessionStore
from services.base_service import BaseService
from services.permissions import Permission
from services.protected_action_service import ProtectedActionService
from utils.time_utils import Clock

MAX_PRODUCT_IMAGE_BYTES = 2 * 1024 * 1024
MAX_PRODUCT_IMAGE_DIMENSION = 4096
EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png"}


@dataclass(frozen=True, slots=True)
class ProductImageResult:
    product_id: int
    image_url: str


def _invalid_image(message: str, *, too_large: bool = False) -> None:
    raise AppError(
        "PRODUCT_IMAGE_TOO_LARGE" if too_large else "INVALID_PRODUCT_IMAGE",
        message,
        {"image": message},
    )


def prepare_product_image(image_bytes: bytes) -> tuple[bytes, str]:
    """Verify real bytes and re-encode pixels without client metadata."""
    if not isinstance(image_bytes, bytes) or not image_bytes:
        _invalid_image("Dữ liệu ảnh sản phẩm không hợp lệ.")
    if len(image_bytes) > MAX_PRODUCT_IMAGE_BYTES:
        _invalid_image(
            "Ảnh sản phẩm không được vượt quá 2 MiB.",
            too_large=True,
        )

    try:
        with warnings.catch_warnings():
            warnings.simplefilter(
                "error",
                Image.DecompressionBombWarning,
            )
            with Image.open(BytesIO(image_bytes)) as check:
                image_format = check.format
                if image_format not in EXTENSIONS:
                    _invalid_image("Chỉ chấp nhận ảnh JPG hoặc PNG.")
                check.verify()

            with Image.open(BytesIO(image_bytes)) as original:
                if original.format != image_format:
                    _invalid_image("Định dạng ảnh không hợp lệ.")
                width, height = original.size
                if (
                    width < 1
                    or height < 1
                    or width > MAX_PRODUCT_IMAGE_DIMENSION
                    or height > MAX_PRODUCT_IMAGE_DIMENSION
                ):
                    _invalid_image(
                        "Kích thước ảnh vượt giới hạn 4096 pixel."
                    )
                if getattr(original, "n_frames", 1) != 1:
                    _invalid_image("Không chấp nhận ảnh động.")

                original.load()
                oriented = ImageOps.exif_transpose(original)
                has_alpha = (
                    image_format == "PNG"
                    and (
                        "A" in oriented.getbands()
                        or "transparency" in oriented.info
                    )
                )
                mode = "RGBA" if has_alpha else "RGB"
                pixels = oriented.convert(mode)
                clean = Image.new(mode, pixels.size)
                clean.paste(pixels)

                output = BytesIO()
                if image_format == "JPEG":
                    clean.save(
                        output,
                        format="JPEG",
                        quality=85,
                        optimize=True,
                    )
                else:
                    clean.save(
                        output,
                        format="PNG",
                        optimize=True,
                    )
    except AppError:
        raise
    except (
        OSError,
        ValueError,
        SyntaxError,
        UnidentifiedImageError,
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
    ) as exc:
        raise AppError(
            "INVALID_PRODUCT_IMAGE",
            "Không thể đọc ảnh sản phẩm hợp lệ.",
            {"image": "Tệp ảnh bị lỗi hoặc sai định dạng."},
        ) from exc

    result = output.getvalue()
    if len(result) > MAX_PRODUCT_IMAGE_BYTES:
        _invalid_image(
            "Ảnh sau xử lý vượt quá 2 MiB.",
            too_large=True,
        )
    return result, EXTENSIONS[image_format]


class ProductImageService(BaseService):
    """Only Admin/Super Admin may attach an uploaded image to a product."""

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        *,
        clock: Clock | None = None,
        image_dir: Path | None = None,
        auth_service: AuthService | None = None,
        protected_actions: ProtectedActionService | None = None,
        repository_factory: Callable[[Session], ProductImageRepository] = (
            ProductImageRepository
        ),
    ) -> None:
        super().__init__(clock=clock)
        auth = auth_service or AuthService(
            session_factory=session_factory,
            clock=clock,
        )
        self.auth_service = auth
        self.protected_actions = (
            protected_actions
            if protected_actions is not None
            else ProtectedActionService(
                session_factory=session_factory,
                auth_service=auth,
            )
        )
        root = Path(__file__).resolve().parents[1]
        assets = Path(
            os.environ.get("FLET_ASSETS_DIR", str(root / "assets"))
        )
        self.image_dir = (
            Path(image_dir)
            if image_dir is not None
            else assets / "products"
        )
        self.repository_factory = repository_factory

    def upload(
        self,
        *,
        session_store: AuthSessionStore,
        product_id: int,
        image_bytes: bytes,
    ) -> ProductImageResult:
        """Guard -> product row lock -> safe image -> file -> DB commit.

        A new file is removed if SQL/action/commit fails. Previously linked
        files are not deleted because they may still be referenced.
        """
        saved_path: Path | None = None

        def action(session: Session) -> ProductImageResult:
            nonlocal saved_path
            if type(product_id) is not int or product_id <= 0:
                raise AppError(
                    "VALIDATION_ERROR",
                    "ID sản phẩm không hợp lệ.",
                    {"product_id": "ID phải là số nguyên dương."},
                )

            repo = self.repository_factory(session)
            if repo.get_by_id(product_id, for_update=True) is None:
                raise AppError("NOT_FOUND", "Không tìm thấy sản phẩm.")

            clean_bytes, suffix = prepare_product_image(image_bytes)
            actor = self.auth_service.require_user(
                session_store=session_store,
            )
            name = f"{uuid4().hex}{suffix}"
            image_url = f"/products/{name}"

            self.image_dir.mkdir(parents=True, exist_ok=True)
            target = self.image_dir / name

            # Register the path before write: cleanup even a partial write.
            with target.open("xb") as stream:
                saved_path = target
                stream.write(clean_bytes)

            if not repo.update_image_url(
                product_id=product_id,
                image_url=image_url,
                now_utc=self.current_time(),
                updated_by=actor.user_id,
            ):
                raise AppError(
                    "NOT_FOUND",
                    "Không tìm thấy sản phẩm.",
                )

            return ProductImageResult(
                product_id=product_id,
                image_url=image_url,
            )

        try:
            return self.protected_actions.run_allowed(
                session_store=session_store,
                permission=Permission.MANAGE_PRODUCTS,
                action=action,
            )
        except Exception:
            if saved_path is not None:
                saved_path.unlink(missing_ok=True)
            raise
