
"""US03 Task 20 - Doi mat khau va upload avatar P2.

Chi thao tac tren tai khoan da xac thuc qua server-side Session.
Khong tin user_id, ten file hay dinh dang do client khai bao.
"""

import os
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import bcrypt
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.orm import Session

from database.connection import SessionLocal
from models.app_error import AppError
from repositories.user_repository import UserRepository
from services.auth_service import AuthService
from services.auth_session import AuthSessionStore
from services.base_service import BaseService
from utils.time_utils import Clock
from utils.validators import (
    validate_confirm_password,
    validate_password,
)

MAX_AVATAR_BYTES = 2 * 1024 * 1024
MAX_AVATAR_DIMENSION = 4096

ALLOWED_FORMATS = {
    "JPEG": ("JPEG", ".jpg"),
    "PNG": ("PNG", ".png"),
}


@dataclass(frozen=True, slots=True)
class AvatarResult:
    """Thong tin anh dai dien, khong chua du lieu anh goc."""

    user_id: int
    avatar_url: str


def _invalid_avatar(message: str) -> None:
    raise AppError(
        "INVALID_AVATAR",
        message,
        {"avatar": message},
    )


def prepare_avatar(image_bytes: bytes) -> tuple[bytes, str]:
    """Kiem tra va ma hoa lai JPG/PNG bang Pillow.

    Khong tin extension, MIME hay ten file do client cung cap.
    Loai bo metadata bang cach tao anh moi.
    """

    if not isinstance(image_bytes, bytes):
        _invalid_avatar("Du lieu anh khong hop le.")

    if not image_bytes:
        _invalid_avatar("Anh dai dien khong duoc de trong.")

    if len(image_bytes) > MAX_AVATAR_BYTES:
        raise AppError(
            "AVATAR_TOO_LARGE",
            "Anh dai dien khong duoc vuot qua 2 MB.",
            {"avatar": "Tep anh vuot qua 2 MB."},
        )

    try:
        with warnings.catch_warnings():
            warnings.simplefilter(
                "error",
                Image.DecompressionBombWarning,
            )

            # verify() kiem tra file, sau do phai mo lai de doc.
            with Image.open(BytesIO(image_bytes)) as check:
                image_format = check.format
                if image_format not in ALLOWED_FORMATS:
                    _invalid_avatar("Chi chap nhan anh JPG hoac PNG.")
                check.verify()

            with Image.open(BytesIO(image_bytes)) as original:
                if original.format != image_format:
                    _invalid_avatar("Dinh dang tep anh khong hop le.")

                width, height = original.size
                if (
                    width < 1
                    or height < 1
                    or width > MAX_AVATAR_DIMENSION
                    or height > MAX_AVATAR_DIMENSION
                ):
                    _invalid_avatar("Kich thuoc anh khong hop le.")

                if getattr(original, "n_frames", 1) != 1:
                    _invalid_avatar("Khong chap nhan anh dong.")

                original.load()
                corrected = ImageOps.exif_transpose(original)

                # Ma hoa lai de khong giu metadata/du lieu dinh kem.
                output = BytesIO()

                if image_format == "JPEG":
                    clean = corrected.convert("RGB")
                    clean.save(
                        output,
                        format="JPEG",
                        quality=85,
                        optimize=True,
                    )
                else:
                    has_alpha = (
                        "A" in corrected.getbands()
                        or "transparency" in corrected.info
                    )
                    clean = corrected.convert(
                        "RGBA" if has_alpha else "RGB"
                    )
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
            "INVALID_AVATAR",
            "Khong the doc anh dai dien hop le.",
            {"avatar": "Tep anh bi loi hoac khong hop le."},
        ) from exc

    cleaned_bytes = output.getvalue()

    if len(cleaned_bytes) > MAX_AVATAR_BYTES:
        raise AppError(
            "AVATAR_TOO_LARGE",
            "Anh sau khi xu ly vuot qua 2 MB.",
            {"avatar": "Vui long chon anh nho hon."},
        )

    extension = ALLOWED_FORMATS[image_format][1]
    return cleaned_bytes, extension


class AccountSecurityService(BaseService):
    """Service P2 xu ly password va avatar."""

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        clock: Clock | None = None,
        avatar_dir: Path | None = None,
    ) -> None:
        super().__init__(clock=clock)
        self.session_factory = session_factory
        self.auth_service = AuthService(
            session_factory=session_factory,
            clock=clock,
        )

        root = Path(__file__).resolve().parents[1]
        assets = Path(
            os.environ.get(
                "FLET_ASSETS_DIR",
                str(root / "assets"),
            )
        )
        self.avatar_dir = Path(
            avatar_dir if avatar_dir is not None else assets / "avatars"
        )

    def change_password(
        self,
        *,
        session_store: AuthSessionStore,
        old_password: str,
        new_password: str,
        confirm_new_password: str,
    ) -> None:
        """Xac minh mat khau cu, thay bcrypt hash va logout.

        Chi thu hoi session hien tai; US16 se xu ly
        viec thu hoi tat ca session tren thiet bi khac.
        """

        current = self.auth_service.require_user(
            session_store=session_store,
        )

        # Validate mat khau moi va xac nhan.
        valid_new = validate_password(new_password)
        validate_confirm_password(
            valid_new,
            confirm_new_password,
        )

        # bcrypt chi chap nhan toi da 72 byte UTF-8.
        if not isinstance(old_password, str):
            raise AppError(
                "INVALID_OLD_PASSWORD",
                "Mat khau cu khong dung.",
            )

        try:
            old_bytes = old_password.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise AppError(
                "INVALID_OLD_PASSWORD",
                "Mat khau cu khong dung.",
            ) from exc

        if not old_bytes or len(old_bytes) > 72:
            raise AppError(
                "INVALID_OLD_PASSWORD",
                "Mat khau cu khong dung.",
            )

        new_bytes = valid_new.encode("utf-8")

        with (
            self.session_factory() as session,
            session.begin(),
        ):
            repository = UserRepository(session)

            # FOR UPDATE giu nhat quan trang thai va hash
            # trong suot transaction.
            user = repository.get_security_by_id(
                current.user_id,
                for_update=True,
            )

            if user is None or user["status"] != "ACTIVE":
                raise AppError(
                    "UNAUTHORIZED",
                    "Tai khoan khong con duoc phep thao tac.",
                )

            stored_hash = user["password_hash"].encode("ascii")

            if not bcrypt.checkpw(old_bytes, stored_hash):
                raise AppError(
                    "INVALID_OLD_PASSWORD",
                    "Mat khau cu khong dung.",
                    {"old_password": "Mat khau cu khong dung."},
                )

            if bcrypt.checkpw(new_bytes, stored_hash):
                raise AppError(
                    "PASSWORD_REUSED",
                    "Mat khau moi phai khac mat khau cu.",
                    {
                        "new_password":
                            "Khong duoc dung lai mat khau cu."
                    },
                )

            new_hash = bcrypt.hashpw(
                new_bytes,
                bcrypt.gensalt(),
            ).decode("ascii")

            repository.update_password_hash(
                user_id=current.user_id,
                password_hash=new_hash,
                now_utc=self.current_time(),
            )

        # Chi xoa session sau khi DB commit thanh cong.
        self.auth_service.logout(
            session_store=session_store,
        )

    def upload_avatar(
        self,
        *,
        session_store: AuthSessionStore,
        image_bytes: bytes,
    ) -> AvatarResult:
        """Kiem tra anh, luu tep UUID va cap nhat avatar_url."""

        current = self.auth_service.require_user(
            session_store=session_store,
        )

        # Phat hien dinh dang bang noi dung anh.
        cleaned_bytes, extension = prepare_avatar(image_bytes)

        # Moi ten file la UUID, khong su dung ten client.
        filename = f"{uuid4().hex}{extension}"
        avatar_url = f"avatars/{filename}"

        self.avatar_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        target = self.avatar_dir / filename

        # xb: tao file moi, khong ghi de file co san.
        with target.open("xb") as output:
            output.write(cleaned_bytes)

        try:
            with (
                self.session_factory() as session,
                session.begin(),
            ):
                repository = UserRepository(session)

                user = repository.get_by_id(
                    current.user_id,
                    for_update=True,
                )

                if user is None or user["status"] != "ACTIVE":
                    raise AppError(
                        "UNAUTHORIZED",
                        "Tai khoan khong con hop le.",
                    )

                repository.update_avatar_url(
                    user_id=current.user_id,
                    avatar_url=avatar_url,
                    now_utc=self.current_time(),
                )

        except Exception:
            # DB loi: khong de lai tep anh moi mo coi.
            target.unlink(missing_ok=True)
            raise

        return AvatarResult(
            user_id=current.user_id,
            avatar_url=avatar_url,
        )
