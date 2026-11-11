
"""Task 38 / US07: atomic stock import, average cost and movement log."""

from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from database.connection import SessionLocal
from models.app_error import AppError
from repositories.import_repository import ImportRepository
from repositories.inventory_repository import InventoryRepository
from repositories.stock_movement_repository import StockMovementRepository
from repositories.supplier_repository import SupplierRepository
from services.auth_service import AuthService
from services.auth_session import AuthSessionStore
from services.base_service import BaseService
from services.catalog_service import CatalogService
from services.permissions import Permission
from services.protected_action_service import ProtectedActionService
from utils.money_utils import quantize_money, weighted_average_cost
from utils.time_utils import Clock

MAX_INT = 2_147_483_647
MAX_MONEY = Decimal("9999999999999999.99")
CENT = Decimal("0.01")


class ImportService(BaseService):
    """A complete import is committed once by ProtectedActionService."""

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        *,
        clock: Clock | None = None,
        auth_service: AuthService | None = None,
        protected_actions: ProtectedActionService | None = None,
        import_repository_factory: Callable[
            [Session], ImportRepository
        ] = ImportRepository,
        inventory_repository_factory: Callable[
            [Session], InventoryRepository
        ] = InventoryRepository,
        movement_repository_factory: Callable[
            [Session], StockMovementRepository
        ] = StockMovementRepository,
        supplier_repository_factory: Callable[
            [Session], SupplierRepository
        ] = SupplierRepository,
    ) -> None:
        super().__init__(clock=clock)

        self.auth_service = auth_service or AuthService(
            session_factory=session_factory,
            clock=clock,
        )

        self.protected_actions = (
            protected_actions
            or ProtectedActionService(
                session_factory=session_factory,
                auth_service=self.auth_service,
            )
        )

        self.import_repository_factory = import_repository_factory
        self.inventory_repository_factory = inventory_repository_factory
        self.movement_repository_factory = movement_repository_factory
        self.supplier_repository_factory = supplier_repository_factory

    @staticmethod
    def _positive_id(value: object, field: str) -> int:
        if type(value) is not int or value <= 0:
            raise AppError(
                "VALIDATION_ERROR",
                "ID không hợp lệ.",
                {field: "Phải là số nguyên dương."},
            )

        return value

    @staticmethod
    def _price(value: object) -> Decimal:
        if type(value) is bool or not isinstance(
            value, (Decimal, str, int)
        ):
            raise AppError(
                "VALIDATION_ERROR",
                "Giá nhập không hợp lệ.",
                {
                    "import_price": (
                        "Dùng Decimal, chuỗi hoặc int; "
                        "không dùng float."
                    )
                },
            )

        try:
            amount = Decimal(
                value.strip() if isinstance(value, str) else value
            )
        except (InvalidOperation, ValueError) as exc:
            raise AppError(
                "VALIDATION_ERROR",
                "Giá nhập không hợp lệ.",
            ) from exc

        if (
            not amount.is_finite()
            or amount <= 0
            or amount > MAX_MONEY
        ):
            raise AppError(
                "VALIDATION_ERROR",
                "Giá nhập phải lớn hơn 0 và trong giới hạn tiền tệ.",
            )

        if amount != amount.quantize(CENT):
            raise AppError(
                "VALIDATION_ERROR",
                "Giá nhập có tối đa hai chữ số thập phân.",
            )

        return quantize_money(amount)

    @classmethod
    def _prepare(
        cls,
        *,
        supplier_id: int,
        items: object,
        note: object,
    ) -> tuple[int, list[dict[str, Any]], Decimal, str | None]:
        cls._positive_id(supplier_id, "supplier_id")

        if not isinstance(items, list) or not items:
            raise AppError(
                "VALIDATION_ERROR",
                "Phiếu nhập cần ít nhất một sản phẩm.",
            )

        if note is not None and not isinstance(note, str):
            raise AppError(
                "VALIDATION_ERROR",
                "Ghi chú không hợp lệ.",
            )

        clean_note = (
            (note.strip() or None)
            if isinstance(note, str)
            else None
        )

        if clean_note is not None and len(clean_note) > 255:
            raise AppError(
                "VALIDATION_ERROR",
                "Ghi chú tối đa 255 ký tự.",
            )

        clean: list[dict[str, Any]] = []
        seen: set[int] = set()
        total = Decimal("0.00")

        for item in items:
            if not isinstance(item, dict):
                raise AppError(
                    "VALIDATION_ERROR",
                    "Dòng nhập phải là một object.",
                )

            product_id = cls._positive_id(
                item.get("product_id"),
                "product_id",
            )
            quantity = item.get("quantity")

            if (
                type(quantity) is not int
                or not 1 <= quantity <= MAX_INT
            ):
                raise AppError(
                    "VALIDATION_ERROR",
                    "Số lượng phải là số nguyên dương hợp lệ.",
                )

            if product_id in seen:
                raise AppError(
                    "VALIDATION_ERROR",
                    "Không được nhập trùng một sản phẩm.",
                )

            seen.add(product_id)
            price = cls._price(item.get("import_price"))

            line_total = Decimal(quantity) * price
            total += line_total

            if total > MAX_MONEY:
                raise AppError(
                    "VALIDATION_ERROR",
                    "Tổng tiền phiếu nhập vượt giới hạn lưu trữ.",
                )

            clean.append(
                {
                    "product_id": product_id,
                    "quantity": quantity,
                    "import_price": price,
                    "line_total": line_total,
                }
            )

        # Bảo đảm thứ tự khóa sản phẩm tăng dần theo ID.
        clean.sort(key=lambda row: row["product_id"])

        return supplier_id, clean, total, clean_note

    def create_import(
        self,
        *,
        session_store: AuthSessionStore,
        supplier_id: int,
        items: list[dict[str, Any]],
        note: str | None = None,
    ) -> dict[str, Any]:
        """Validate then execute all writes in one guarded DB transaction."""
        supplier_id, lines, total, note = self._prepare(
            supplier_id=supplier_id,
            items=items,
            note=note,
        )

        def action(session: Session) -> dict[str, Any]:
            # ProtectedActionService đã kiểm tra và khóa tài khoản.
            actor = self.auth_service.require_user(
                session_store=session_store
            )
            actor_id = actor.user_id

            # Chặn nhà cung cấp đã ngừng hợp tác.
            CatalogService.require_active_for_import(
                repository=self.supplier_repository_factory(session),
                supplier_id=supplier_id,
            )

            inventory = self.inventory_repository_factory(session)
            imports = self.import_repository_factory(session)
            movements = self.movement_repository_factory(session)

            timestamp = self.current_time()

            # Khóa toàn bộ sản phẩm theo ID tăng dần trước khi ghi.
            locked: dict[int, dict[str, Any]] = {}

            for line in lines:
                product_id = line["product_id"]
                row = inventory.get_for_update(product_id)

                if row is None:
                    raise AppError(
                        "NOT_FOUND",
                        "Không tìm thấy sản phẩm nhập kho.",
                    )

                if row["status"] != "ACTIVE":
                    raise AppError(
                        "PRODUCT_INACTIVE",
                        "Sản phẩm đã ngừng kinh doanh.",
                    )

                if row["stock"] + line["quantity"] > MAX_INT:
                    raise AppError(
                        "STOCK_OVERFLOW",
                        "Tồn kho vượt giới hạn số nguyên.",
                    )

                locked[product_id] = row

            # Bước 1: Tạo phiếu với mã tạm ngẫu nhiên.
            receipt_id = imports.create_receipt(
                temporary_code=f"TMP-{uuid4().hex}",
                supplier_id=supplier_id,
                import_date=timestamp,
                total_amount=total,
                note=note,
                created_by=actor_id,
                created_at=timestamp,
            )

            # Bước 2: Sinh mã phiếu chính thức từ ID.
            code = f"PN{receipt_id:08d}"

            if not imports.update_code(
                receipt_id=receipt_id,
                code=code,
            ):
                raise RuntimeError(
                    "Không cập nhật được mã phiếu nhập"
                )

            # Bước 3: Lưu chi tiết, cập nhật tồn và ghi movement.
            for line in lines:
                product_id = line["product_id"]
                old = locked[product_id]

                stock_after = old["stock"] + line["quantity"]

                new_cost = weighted_average_cost(
                    old["stock"],
                    old["cost_price"],
                    line["quantity"],
                    line["import_price"],
                )

                imports.create_item(
                    receipt_id=receipt_id,
                    **line,
                )

                updated = inventory.set_balance(
                    product_id=product_id,
                    stock=stock_after,
                    cost_price=new_cost,
                    updated_at=timestamp,
                    updated_by=actor_id,
                )

                if not updated:
                    raise RuntimeError(
                        "Không cập nhật được tồn kho"
                    )

                movements.record_import(
                    receipt_id=receipt_id,
                    product_id=product_id,
                    quantity=line["quantity"],
                    stock_after=stock_after,
                    created_at=timestamp,
                    created_by=actor_id,
                )

            return {
                "id": receipt_id,
                "code": code,
                "total_amount": total,
            }

        return self.protected_actions.run_allowed(
            session_store=session_store,
            permission=Permission.IMPORT_STOCK,
            action=action,
        )
