
"""US06 Task 34: ngừng hợp tác, không xóa nhà cung cấp."""

from sqlalchemy import text

from repositories.supplier_repository import SupplierRepository


class SupplierStatusRepository(SupplierRepository):
    """Repository chỉ thay đổi trạng thái hợp tác."""

    def deactivate(self, *, supplier_id: int) -> bool:
        result = self.session.execute(
            text("""
                UPDATE suppliers
                SET is_active = 0
                WHERE id = :supplier_id
                  AND is_active = 1
            """),
            {"supplier_id": supplier_id},
        )
        return result.rowcount == 1
