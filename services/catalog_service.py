
"""US06 Task 34: Catalog Service và ngừng hợp tác nhà cung cấp."""

import re
from collections.abc import Callable
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.connection import SessionLocal
from models.app_error import AppError
from repositories.brand_repository import BrandRepository
from repositories.supplier_repository import SupplierRepository
from repositories.supplier_status_repository import SupplierStatusRepository
from services.auth_service import AuthService
from services.auth_session import AuthSessionStore
from services.base_service import BaseService
from services.permissions import Permission
from services.protected_action_service import ProtectedActionService
from utils.time_utils import Clock


class CatalogService(BaseService):
    """Hãng và NCC: đọc, thêm, sửa, ngừng hợp tác an toàn."""

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        *,
        clock: Clock | None = None,
        auth_service: AuthService | None = None,
        protected_actions: ProtectedActionService | None = None,
        brand_repository_factory: Callable[
            [Session], BrandRepository
        ] = BrandRepository,
        supplier_repository_factory: Callable[
            [Session], SupplierRepository
        ] = SupplierRepository,
        status_repository_factory: Callable[
            [Session], SupplierStatusRepository
        ] = SupplierStatusRepository,
    ) -> None:
        super().__init__(clock=clock)
        self.session_factory = session_factory

        auth = (
            auth_service
            if auth_service is not None
            else AuthService(
                session_factory=session_factory,
                clock=clock,
            )
        )

        self.protected_actions = (
            protected_actions
            if protected_actions is not None
            else ProtectedActionService(
                session_factory=session_factory,
                auth_service=auth,
            )
        )

        self.brand_repository_factory = brand_repository_factory
        self.supplier_repository_factory = supplier_repository_factory
        self.status_repository_factory = status_repository_factory

    @staticmethod
    def _positive_id(value: object, field: str) -> int:
        if type(value) is not int or value <= 0:
            raise AppError(
                "VALIDATION_ERROR",
                "Mã định danh không hợp lệ.",
                {field: "Phải là số nguyên dương."},
            )
        return value

    @staticmethod
    def _page(limit: int, offset: int) -> None:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise AppError(
                "VALIDATION_ERROR",
                "Giới hạn phân trang không hợp lệ.",
                {"limit": "Phải từ 1 đến 100."},
            )
        if type(offset) is not int or offset < 0:
            raise AppError(
                "VALIDATION_ERROR",
                "Vị trí trang không hợp lệ.",
                {"offset": "Phải là số nguyên không âm."},
            )

    @staticmethod
    def _required_text(
        value: object,
        *,
        field: str,
        max_length: int,
    ) -> str:
        if not isinstance(value, str):
            raise AppError(
                "VALIDATION_ERROR",
                "Thông tin không hợp lệ.",
                {field: "Phải nhập văn bản."},
            )

        normalized = " ".join(value.split())

        if not normalized or len(normalized) > max_length:
            raise AppError(
                "VALIDATION_ERROR",
                "Thông tin không hợp lệ.",
                {
                    field: (
                        f"Phải nhập từ 1 đến {max_length} ký tự."
                    )
                },
            )
        return normalized

    @staticmethod
    def _optional_text(
        value: object,
        *,
        field: str,
        max_length: int,
    ) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise AppError(
                "VALIDATION_ERROR",
                "Thông tin không hợp lệ.",
                {field: "Phải là văn bản."},
            )

        normalized = " ".join(value.split())
        if len(normalized) > max_length:
            raise AppError(
                "VALIDATION_ERROR",
                "Thông tin không hợp lệ.",
                {field: f"Không vượt quá {max_length} ký tự."},
            )
        return normalized or None

    @classmethod
    def _phone(cls, value: object) -> str | None:
        phone = cls._optional_text(
            value, field="phone", max_length=10
        )
        if phone is not None and not (
            len(phone) == 10
            and phone.isascii()
            and phone.isdigit()
        ):
            raise AppError(
                "VALIDATION_ERROR",
                "Số điện thoại không hợp lệ.",
                {"phone": "Cần đúng 10 chữ số."},
            )
        return phone

    @classmethod
    def _email(cls, value: object) -> str | None:
        email = cls._optional_text(
            value, field="email", max_length=100
        )
        if email is None:
            return None

        email = email.lower()
        if not re.fullmatch(
            r"[^@\s]+@[^@\s]+\.[^@\s]+",
            email,
        ):
            raise AppError(
                "VALIDATION_ERROR",
                "Email không hợp lệ.",
                {"email": "Sai định dạng email."},
            )
        return email

    @staticmethod
    def _is_brand_unique_error(exc: IntegrityError) -> bool:
        """Chỉ chuyển lỗi UNIQUE đúng constraint tên hãng."""
        args = getattr(exc.orig, "args", ())
        code = args[0] if args else None
        detail = str(exc.orig).lower()
        return (
            code == 1062
            and "uq_brands_name" in detail
        )

    @staticmethod
    def _brand_exists() -> AppError:
        return AppError(
            "BRAND_EXISTS",
            "Tên hãng đã tồn tại.",
            {"name": "Vui lòng nhập tên hãng khác."},
        )

    # ==========================================================
    # HÃNG SẢN XUẤT
    # ==========================================================

    def list_brands(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Danh sách tên hãng là dữ liệu danh mục công khai."""
        self._page(limit, offset)
        with self.session_factory() as session:
            return self.brand_repository_factory(
                session
            ).list_brands(limit=limit, offset=offset)

    def get_brand(
        self,
        *,
        brand_id: int,
    ) -> dict[str, Any]:
        self._positive_id(brand_id, "brand_id")

        with self.session_factory() as session:
            row = self.brand_repository_factory(
                session
            ).get_by_id(brand_id)

        if row is None:
            raise AppError(
                "NOT_FOUND", "Không tìm thấy hãng."
            )
        return row

    def save_brand(
        self,
        *,
        session_store: AuthSessionStore,
        name: str,
        brand_id: int | None = None,
    ) -> dict[str, Any]:
        """Thêm hoặc sửa hãng; chỉ Admin/Super Admin."""
        cleaned = self._required_text(
            name, field="name", max_length=100
        )

        if brand_id is not None:
            self._positive_id(brand_id, "brand_id")

        def action(session: Session) -> dict[str, Any]:
            repo = self.brand_repository_factory(session)

            if brand_id is None:
                if repo.find_by_name(cleaned) is not None:
                    raise self._brand_exists()

                new_id = repo.create(
                    name=cleaned,
                    now_utc=self.current_time(),
                )
                result = repo.get_by_id(new_id)
            else:
                current = repo.get_by_id(
                    brand_id, for_update=True
                )
                if current is None:
                    raise AppError(
                        "NOT_FOUND",
                        "Không tìm thấy hãng cần sửa.",
                    )

                if current["name"] == cleaned:
                    return current

                if repo.find_by_name(
                    cleaned, exclude_id=brand_id
                ) is not None:
                    raise self._brand_exists()

                if not repo.update_name(
                    brand_id=brand_id,
                    name=cleaned,
                ):
                    raise AppError(
                        "NOT_FOUND",
                        "Không tìm thấy hãng cần sửa.",
                    )
                result = repo.get_by_id(brand_id)

            if result is None:
                raise AppError(
                    "NOT_FOUND",
                    "Không đọc được hãng sau khi lưu.",
                )
            return result

        try:
            return self.protected_actions.run_allowed(
                session_store=session_store,
                permission=Permission.MANAGE_BRANDS,
                action=action,
            )
        except IntegrityError as exc:
            if self._is_brand_unique_error(exc):
                raise self._brand_exists() from exc
            raise

    # ==========================================================
    # NHÀ CUNG CẤP
    # ==========================================================

    def list_suppliers(
        self,
        *,
        session_store: AuthSessionStore,
        is_active: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        self._page(limit, offset)
        if is_active is not None and type(is_active) is not bool:
            raise AppError(
                "VALIDATION_ERROR",
                "Bộ lọc trạng thái không hợp lệ.",
                {"is_active": "Chỉ chấp nhận True/False/None."},
            )

        return self.protected_actions.run_allowed(
            session_store=session_store,
            permission=Permission.MANAGE_SUPPLIERS,
            action=lambda session: (
                self.supplier_repository_factory(
                    session
                ).list_suppliers(
                    is_active=is_active,
                    limit=limit,
                    offset=offset,
                )
            ),
        )

    def get_supplier(
        self,
        *,
        session_store: AuthSessionStore,
        supplier_id: int,
    ) -> dict[str, Any]:
        self._positive_id(supplier_id, "supplier_id")

        def action(session: Session) -> dict[str, Any]:
            row = self.supplier_repository_factory(
                session
            ).get_by_id(supplier_id)
            if row is None:
                raise AppError(
                    "NOT_FOUND",
                    "Không tìm thấy nhà cung cấp.",
                )
            return row

        return self.protected_actions.run_allowed(
            session_store=session_store,
            permission=Permission.MANAGE_SUPPLIERS,
            action=action,
        )

    def save_supplier(
        self,
        *,
        session_store: AuthSessionStore,
        name: str,
        phone: str | None = None,
        email: str | None = None,
        address: str | None = None,
        supplier_id: int | None = None,
    ) -> dict[str, Any]:
        """Thêm/sửa thông tin, tuyệt đối không sửa is_active."""
        cleaned_name = self._required_text(
            name, field="name", max_length=150
        )
        cleaned_phone = self._phone(phone)
        cleaned_email = self._email(email)
        cleaned_address = self._optional_text(
            address, field="address", max_length=255
        )

        if supplier_id is not None:
            self._positive_id(supplier_id, "supplier_id")

        def action(session: Session) -> dict[str, Any]:
            repo = self.supplier_repository_factory(session)

            if supplier_id is None:
                saved_id = repo.create(
                    name=cleaned_name,
                    phone=cleaned_phone,
                    email=cleaned_email,
                    address=cleaned_address,
                )
            else:
                current = repo.get_by_id(
                    supplier_id, for_update=True
                )
                if current is None:
                    raise AppError(
                        "NOT_FOUND",
                        "Không tìm thấy nhà cung cấp cần sửa.",
                    )

                updated = repo.update_details(
                    supplier_id=supplier_id,
                    name=cleaned_name,
                    phone=cleaned_phone,
                    email=cleaned_email,
                    address=cleaned_address,
                )
                if not updated:
                    raise AppError(
                        "NOT_FOUND",
                        "Không tìm thấy nhà cung cấp cần sửa.",
                    )
                saved_id = supplier_id

            result = repo.get_by_id(saved_id)
            if result is None:
                raise AppError(
                    "NOT_FOUND",
                    "Không đọc được nhà cung cấp sau khi lưu.",
                )
            return result

        return self.protected_actions.run_allowed(
            session_store=session_store,
            permission=Permission.MANAGE_SUPPLIERS,
            action=action,
        )

    def discontinue_supplier(
        self,
        *,
        session_store: AuthSessionStore,
        supplier_id: int,
    ) -> dict[str, Any]:
        """Ngừng hợp tác nhưng không xóa nhà cung cấp/lịch sử."""
        self._positive_id(supplier_id, "supplier_id")

        def action(session: Session) -> dict[str, Any]:
            repo = self.supplier_repository_factory(session)
            current = repo.get_by_id(
                supplier_id, for_update=True
            )

            if current is None:
                raise AppError(
                    "NOT_FOUND",
                    "Không tìm thấy nhà cung cấp.",
                )

            if not bool(current["is_active"]):
                return current

            status_repo = self.status_repository_factory(session)
            if not status_repo.deactivate(
                supplier_id=supplier_id
            ):
                raise AppError(
                    "NOT_FOUND",
                    "Không cập nhật được trạng thái hợp tác.",
                )

            result = repo.get_by_id(supplier_id)
            if result is None:
                raise AppError(
                    "NOT_FOUND",
                    "Không đọc được nhà cung cấp sau cập nhật.",
                )
            return result

        return self.protected_actions.run_allowed(
            session_store=session_store,
            permission=Permission.MANAGE_SUPPLIERS,
            action=action,
        )

    @classmethod
    def require_active_for_import(
        cls,
        *,
        repository: SupplierRepository,
        supplier_id: int,
    ) -> dict[str, Any]:
        """Điều kiện cho US07, gọi trong transaction nhập kho."""
        cls._positive_id(supplier_id, "supplier_id")

        supplier = repository.get_by_id(
            supplier_id, for_update=True
        )
        if supplier is None:
            raise AppError(
                "NOT_FOUND", "Không tìm thấy nhà cung cấp."
            )
        if not bool(supplier["is_active"]):
            raise AppError(
                "SUPPLIER_INACTIVE",
                "Nhà cung cấp đã ngừng hợp tác.",
            )
        return supplier
