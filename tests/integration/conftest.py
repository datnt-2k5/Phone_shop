
"""Cấu hình kết nối Integration Test cho Task 7.

Chỉ cho phép chạy trên database phone_shop_test.
Không sử dụng Engine của database chính để ghi dữ liệu.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import URL, Connection, Engine

from database.connection import ensure_strict_mode

# Lấy đường dẫn thư mục gốc phone_shop
ROOT = Path(__file__).resolve().parents[2]

# Database và tài khoản bắt buộc
EXPECTED_DB = "phone_shop_test"
EXPECTED_USER = "phone_shop_tester"

# Danh sách 11 bảng phải có
REQUIRED_TABLES = {
    "users",
    "brands",
    "suppliers",
    "products",
    "import_receipts",
    "import_items",
    "orders",
    "order_items",
    "invoices",
    "stock_movements",
    "settings",
}


def build_isolated_test_engine() -> Engine:
    """Tạo kết nối riêng, an toàn cho kiểm thử."""

    # Đọc cấu hình từ file .env
    config = dotenv_values(ROOT / ".env")

    # Chỉ cho phép môi trường development
    if config.get("APP_ENV") != "dev":
        raise RuntimeError(
            "Integration Test chỉ chạy khi APP_ENV=dev"
        )

    # Không cho thay database chính bằng DB test
    if config.get("DB_NAME") != "phone_shop":
        raise RuntimeError(
            "DB_NAME ứng dụng phải là phone_shop"
        )

    # Chỉ kiểm thử MariaDB trên máy hiện tại
    if config.get("DB_HOST") not in {
        "127.0.0.1",
        "localhost",
    }:
        raise RuntimeError(
            "Chỉ cho phép kết nối MariaDB cục bộ"
        )

    # Bắt buộc dùng tài khoản tester
    if config.get("TEST_DB_USER") != EXPECTED_USER:
        raise RuntimeError(
            "TEST_DB_USER phải là phone_shop_tester"
        )

    password = config.get("TEST_DB_PASSWORD")

    if not password:
        raise RuntimeError(
            "Thiếu TEST_DB_PASSWORD trong .env"
        )

    # Xây dựng URL kết nối an toàn
    url = URL.create(
        drivername="mysql+pymysql",
        username=EXPECTED_USER,
        password=password,
        host="127.0.0.1",
        port=int(config.get("DB_PORT") or "3307"),
        database=EXPECTED_DB,
        query={"charset": "utf8mb4"},
    )

    # Tạo Engine dành riêng cho test
    engine = create_engine(
        url,
        pool_pre_ping=True,
    )

    # Sử dụng Strict Mode như ứng dụng chính
    event.listen(
        engine,
        "connect",
        ensure_strict_mode,
        insert=True,
    )

    return engine


@pytest.fixture(scope="session")
def test_db_engine() -> Iterator[Engine]:
    """Kiểm tra kết nối trước khi cho phép chạy test."""

    engine = build_isolated_test_engine()

    try:
        with engine.connect() as connection:
            actual_db = connection.execute(
                text("SELECT DATABASE()")
            ).scalar_one()

            current_user = connection.execute(
                text("SELECT CURRENT_USER()")
            ).scalar_one()

            # Ngăn ghi nhầm database
            if actual_db != EXPECTED_DB:
                raise RuntimeError(
                    f"SAI DATABASE: {actual_db}"
                )

            # Ngăn dùng nhầm tài khoản ứng dụng
            db_username = current_user.split("@", 1)[0]

            if db_username != EXPECTED_USER:
                raise RuntimeError(
                    f"SAI TAI KHOAN: {current_user}"
                )

            # Kiểm tra đủ 11 bảng P1
            result = connection.execute(
                text("""
                    SELECT TABLE_NAME
                    FROM information_schema.TABLES
                    WHERE TABLE_SCHEMA = :db
                      AND TABLE_TYPE = 'BASE TABLE'
                """),
                {"db": EXPECTED_DB},
            )

            actual_tables = set(result.scalars())

            missing = REQUIRED_TABLES - actual_tables

            if missing:
                raise RuntimeError(
                    "phone_shop_test thiếu bảng: "
                    + ", ".join(sorted(missing))
                )

        yield engine

    finally:
        engine.dispose()


@pytest.fixture
def test_db(
    test_db_engine: Engine,
) -> Iterator[Connection]:
    """Mỗi bài test có transaction riêng và rollback."""

    with test_db_engine.connect() as connection:
        transaction = connection.begin()

        try:
            database = connection.execute(
                text("SELECT DATABASE()")
            ).scalar_one()

            assert database == EXPECTED_DB

            # Cung cấp connection cho bài kiểm thử
            yield connection

        finally:
            # Không lưu dữ liệu kiểm thử
            if transaction.is_active:
                transaction.rollback()
