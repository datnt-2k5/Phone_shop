
"""Integration Test Task 7 trên MariaDB phone_shop_test.

Không DROP, TRUNCATE hoặc thay đổi database chính.
Dữ liệu được tạo trong transaction và rollback sau test.
"""

from datetime import UTC, datetime
from decimal import Decimal
from secrets import token_urlsafe
from uuid import uuid4

import bcrypt
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from .conftest import REQUIRED_TABLES

# --------------------------------------------------
# A. CÁC HÀM HỖ TRỢ
# --------------------------------------------------


def _now_utc() -> datetime:
    """Lấy giờ UTC, bỏ timezone để lưu vào DATETIME."""
    return datetime.now(UTC).replace(tzinfo=None)


def _unique(label: str) -> str:
    """Tạo tên thử nghiệm khác nhau giữa các lần chạy."""
    return f"T7_{label}_{uuid4().hex[:12]}"


def _assert_db_error(
    exc: DBAPIError,
    expected: int,
) -> None:
    """Kiểm tra đúng mã lỗi do MariaDB trả về."""

    code = exc.orig.args[0] if exc.orig.args else None

    assert code == expected, (
        f"Mong đợi lỗi {expected}, "
        f"thực tế là {code}: {exc.orig}"
    )


def _create_brand(test_db: Connection) -> int:
    """Tạo hãng thử nghiệm trong transaction."""

    result = test_db.execute(
        text("""
            INSERT INTO brands (name, created_at)
            VALUES (:name, :created)
        """),
        {
            "name": _unique("BRAND"),
            "created": _now_utc(),
        },
    )

    assert result.lastrowid is not None
    return int(result.lastrowid)


def _create_product(
    test_db: Connection,
    brand_id: int,
) -> int:
    """Tạo sản phẩm thử nghiệm, tồn kho ban đầu bằng 0."""

    result = test_db.execute(
        text("""
            INSERT INTO products (
                sku,
                name,
                brand_id,
                storage,
                color,
                sell_price,
                cost_price,
                stock,
                min_stock,
                status,
                created_at,
                updated_at
            )
            VALUES (
                :sku,
                :name,
                :brand_id,
                '128GB',
                'Black',
                :sell_price,
                0,
                0,
                0,
                'ACTIVE',
                :now,
                :now
            )
        """),
        {
            "sku": _unique("SKU"),
            "name": _unique("PHONE"),
            "brand_id": brand_id,
            "sell_price": Decimal("1500000.00"),
            "now": _now_utc(),
        },
    )

    assert result.lastrowid is not None
    return int(result.lastrowid)


# --------------------------------------------------
# B. KIỂM TRA DATABASE
# --------------------------------------------------


def test_db01_mariadb_version(
    test_db: Connection,
) -> None:
    """DB01: Kiểm tra MariaDB 10.4.32."""

    version = test_db.execute(
        text("SELECT VERSION()")
    ).scalar_one()

    assert version.startswith("10.4.32-MariaDB"), (
        f"Sai phiên bản MariaDB: {version}"
    )


def test_db02_all_tables_use_innodb(
    test_db: Connection,
) -> None:
    """DB02: Các bảng P1 phải dùng InnoDB."""

    result = test_db.execute(
        text("""
            SELECT
                TABLE_NAME,
                ENGINE,
                TABLE_COLLATION
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = 'phone_shop_test'
              AND TABLE_TYPE = 'BASE TABLE'
        """)
    ).mappings().all()

    rows = {
        row["TABLE_NAME"]: row
        for row in result
    }

    # Kiểm tra đủ 11 bảng
    assert REQUIRED_TABLES.issubset(rows)

    for name in REQUIRED_TABLES:
        assert rows[name]["ENGINE"] == "InnoDB"

        assert (
            rows[name]["TABLE_COLLATION"]
            == "utf8mb4_unicode_ci"
        )


# --------------------------------------------------
# C. KIỂM TRA RÀNG BUỘC CHECK
# --------------------------------------------------


def test_db03_check_stock_rejects_negative(
    test_db: Connection,
) -> None:
    """DB03: Không cho cập nhật tồn kho âm."""

    brand_id = _create_brand(test_db)
    product_id = _create_product(test_db, brand_id)

    with pytest.raises(DBAPIError) as caught, test_db.begin_nested():
        test_db.execute(
            text("""
                UPDATE products
                SET stock = -1
                WHERE id = :id
            """),
            {"id": product_id},
        )

    # MariaDB CHECK constraint failed
    _assert_db_error(caught.value, 4025)

    # Sau lỗi, tồn kho vẫn phải bằng 0
    stock = test_db.execute(
        text("""
            SELECT stock
            FROM products
            WHERE id = :id
        """),
        {"id": product_id},
    ).scalar_one()

    assert stock == 0


# --------------------------------------------------
# D. KIỂM TRA NOT NULL
# --------------------------------------------------


def test_db04_not_null_rejects_null(
    test_db: Connection,
) -> None:
    """DB04: Không cho tên hãng bằng NULL."""

    with pytest.raises(DBAPIError) as caught, test_db.begin_nested():
        test_db.execute(
            text("""
                    INSERT INTO brands (
                        name,
                        created_at
                    )
                    VALUES (NULL, :now)
                """),
            {"now": _now_utc()},
        )

    # MariaDB Column cannot be null
    _assert_db_error(caught.value, 1048)


# --------------------------------------------------
# E. KIỂM TRA STRICT MODE
# --------------------------------------------------


def test_db05_strict_mode_on_sqlalchemy_connection(
    test_db: Connection,
) -> None:
    """DB05: SQL Mode có STRICT_TRANS_TABLES hoặc STRICT_ALL_TABLES."""

    sql_mode = test_db.execute(
        text("SELECT @@SESSION.sql_mode")
    ).scalar_one()

    modes = {
        mode.strip().upper()
        for mode in sql_mode.split(",")
    }

    assert {
        "STRICT_TRANS_TABLES",
        "STRICT_ALL_TABLES",
    } & modes


def test_db06_strict_rejects_too_long_varchar(
    test_db: Connection,
) -> None:
    """DB06: brands.name dài tối đa 100 ký tự."""

    with pytest.raises(DBAPIError) as caught, test_db.begin_nested():
        test_db.execute(
            text("""
                    INSERT INTO brands (
                        name,
                        created_at
                    )
                    VALUES (:name, :now)
                """),
            {
                "name": "X" * 101,
                "now": _now_utc(),
            },
        )

    # MariaDB Data too long
    _assert_db_error(caught.value, 1406)


# --------------------------------------------------
# F. KIỂM TRA UNIQUE
# --------------------------------------------------


def test_db09_unique_brand_rejects_duplicate(
    test_db: Connection,
) -> None:
    """DB09: Không cho hai hãng trùng tên."""

    name = _unique("DUPLICATE")

    values = {
        "name": name,
        "now": _now_utc(),
    }

    query = text("""
        INSERT INTO brands (name, created_at)
        VALUES (:name, :now)
    """)

    # Thêm hãng lần thứ nhất: hợp lệ
    test_db.execute(query, values)

    # Thêm lần thứ hai: phải bị từ chối
    with pytest.raises(DBAPIError) as caught, test_db.begin_nested():
        test_db.execute(query, values)

    # MariaDB Duplicate entry
    _assert_db_error(caught.value, 1062)


# --------------------------------------------------
# G. KIỂM TRA FOREIGN KEY
# --------------------------------------------------


def test_foreign_key_rejects_missing_brand(
    test_db: Connection,
) -> None:
    """Không cho sản phẩm tham chiếu tới hãng không tồn tại."""

    with pytest.raises(DBAPIError) as caught, test_db.begin_nested():
        test_db.execute(
            text("""
                    INSERT INTO products (
                        sku,
                        name,
                        brand_id,
                        storage,
                        color,
                        sell_price,
                        cost_price,
                        stock,
                        min_stock,
                        status,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        :sku,
                        :name,
                        -1,
                        '128GB',
                        'Black',
                        1000000,
                        0,
                        0,
                        0,
                        'ACTIVE',
                        :now,
                        :now
                    )
                """),
            {
                "sku": _unique("NO_BRAND"),
                "name": "Foreign Key Test",
                "now": _now_utc(),
            },
        )

    # MariaDB: Cannot add/update child row
    _assert_db_error(caught.value, 1452)


# --------------------------------------------------
# H. KIỂM TRA STOCK MOVEMENT
# --------------------------------------------------


def test_stock_movement_zero_rejected(
    test_db: Connection,
) -> None:
    """Không cho nhật ký biến động kho có quantity_change = 0."""

    brand_id = _create_brand(test_db)
    product_id = _create_product(test_db, brand_id)

    # Mật khẩu ngẫu nhiên chỉ để tạo user thử nghiệm
    password_hash = bcrypt.hashpw(
        token_urlsafe(24).encode("utf-8"),
        bcrypt.gensalt(rounds=4),
    ).decode("ascii")

    # Stock movement cần created_by tham chiếu users
    user = test_db.execute(
        text("""
            INSERT INTO users (
                email,
                password_hash,
                full_name,
                phone,
                role,
                status,
                created_at,
                updated_at
            )
            VALUES (
                :email,
                :hash,
                'Task 7 Tester',
                '0900000000',
                'ADMIN',
                'ACTIVE',
                :now,
                :now
            )
        """),
        {
            "email": (
                _unique("USER").lower()
                + "@example.test"
            ),
            "hash": password_hash,
            "now": _now_utc(),
        },
    )

    assert user.lastrowid is not None

    # Cố tình ghi biến động bằng 0
    with pytest.raises(DBAPIError) as caught, test_db.begin_nested():
        test_db.execute(
            text("""
                    INSERT INTO stock_movements (
                        product_id,
                        type,
                        quantity_change,
                        stock_after,
                        ref_type,
                        ref_id,
                        operation_key,
                        created_at,
                        created_by
                    )
                    VALUES (
                        :product_id,
                        'IMPORT',
                        0,
                        0,
                        'TEST',
                        1,
                        :key,
                        :now,
                        :created_by
                    )
                """),
            {
                "product_id": product_id,
                "key": _unique("MOVE"),
                "now": _now_utc(),
                "created_by": int(user.lastrowid),
            },
        )

    # CHECK quantity_change <> 0
    _assert_db_error(caught.value, 4025)
