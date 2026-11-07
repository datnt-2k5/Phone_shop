"""Kiểm tra cấu trúc P1 không sửa dữ liệu. Chạy: python -m database.check_schema"""

from sqlalchemy import text

from database.connection import engine

EXPECTED_TABLES = {
    "users", "brands", "suppliers", "products", "import_receipts",
    "import_items", "orders", "order_items", "invoices",
    "stock_movements", "settings",
}

REQUIRED_NOT_NULL = {
    "users": {"email", "password_hash", "full_name", "phone", "role", "status", "created_at", "updated_at"},
    "products": {"sku", "name", "brand_id", "storage", "color", "sell_price", "cost_price", "stock", "min_stock", "status", "created_at", "updated_at"},
    "orders": {"code", "customer_id", "idempotency_key", "request_hash", "status", "receiver_name", "receiver_phone", "receiver_address", "total_amount", "created_at", "updated_at"},
    "order_items": {"order_id", "product_id", "product_name", "brand_name", "quantity", "unit_price"},
    "stock_movements": {"product_id", "type", "quantity_change", "stock_after", "ref_type", "ref_id", "operation_key", "created_at", "created_by"},
}


def main() -> None:
    with engine.connect() as connection:
        db_name = connection.execute(text("SELECT DATABASE() ")).scalar_one()
        tables = connection.execute(text("""
            SELECT table_name, engine, table_collation
            FROM information_schema.tables
            WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE'
        """)).mappings().all()
        found_tables = {row["table_name"] for row in tables}
        missing_tables = EXPECTED_TABLES - found_tables

        constraints = connection.execute(text("""
            SELECT constraint_type, COUNT(*) AS total
            FROM information_schema.table_constraints
            WHERE constraint_schema = DATABASE()
            GROUP BY constraint_type
        """)).all()
        constraint_counts = dict(constraints)

        columns = connection.execute(text("""
            SELECT table_name, column_name, is_nullable
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
        """)).mappings().all()
        not_null_fields = {
            (row["table_name"], row["column_name"])
            for row in columns if row["is_nullable"] == "NO"
        }
        missing_not_null = {
            (table, col)
            for table, required_cols in REQUIRED_NOT_NULL.items()
            for col in required_cols
            if (table, col) not in not_null_fields
        }

        print("Database:", db_name)
        print("Số bảng P1 tìm thấy:", len(EXPECTED_TABLES & found_tables), "/ 11")
        print("Ràng buộc:", constraint_counts)
        if missing_tables:
            print("THIẾU BẢNG:", sorted(missing_tables))
        if missing_not_null:
            print("THIẾU NOT NULL:", sorted(missing_not_null))

        non_innodb = [r["table_name"] for r in tables
                      if r["table_name"] in EXPECTED_TABLES and r["engine"].upper() != "INNODB"]
        wrong_collation = [r["table_name"] for r in tables
                           if r["table_name"] in EXPECTED_TABLES and r["table_collation"] != "utf8mb4_unicode_ci"]
        if non_innodb:
            print("Bảng không dùng InnoDB:", non_innodb)
        if wrong_collation:
            print("Bảng sai collation:", wrong_collation)

        for kind in ["FOREIGN KEY", "UNIQUE", "CHECK"]:
            if constraint_counts.get(kind, 0) == 0:
                raise RuntimeError(f"Không tìm thấy ràng buộc {kind}")
        if missing_tables or missing_not_null or non_innodb or wrong_collation:
            raise RuntimeError("Schema chưa đạt yêu cầu P1")
        print("SCHEMA P1: OK")

        if db_name == "phone_shop":
            setting = connection.execute(text("""
                SELECT setting_value FROM settings
                WHERE setting_key = 'ORDER_CANCEL_WINDOW_MINUTES'
            """)).scalar_one_or_none()
            sa = connection.execute(text("""
                SELECT COUNT(*) FROM users WHERE role = 'SUPER_ADMIN'
            """)).scalar_one()
            print("ORDER_CANCEL_WINDOW_MINUTES:", setting)
            print("Số Super Admin:", sa)
            if setting is None or sa != 1:
                raise RuntimeError("Chưa seed cấu hình hoặc Super Admin đúng cách")
            print("SEED P1: OK")


if __name__ == "__main__":
    main()
