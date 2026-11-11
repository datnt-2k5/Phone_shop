
"""Task 41: atomicity, DB constraints and real MariaDB concurrency.

Uses only phone_shop_test. Concurrent tests require independent DB sessions.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from secrets import token_hex
from threading import Barrier, Event, Lock, get_ident
from time import sleep

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from repositories.brand_repository import BrandRepository
from repositories.import_repository import ImportRepository
from repositories.inventory_repository import InventoryRepository
from repositories.product_repository import ProductRepository
from repositories.stock_movement_repository import StockMovementRepository
from repositories.supplier_repository import SupplierRepository
from services.auth_service import AuthService
from services.import_service import ImportService
from utils.time_utils import FixedClock

NOW = datetime(2026, 11, 11, 3, 0, tzinfo=UTC)
DB_NOW = NOW.replace(tzinfo=None)
PASSWORD = "MatKhau123!"


class Store:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value

    def remove(self, key):
        self.values.pop(key, None)


def item(product_id, quantity=1, price="100.00"):
    return {
        "product_id": product_id,
        "quantity": quantity,
        "import_price": price,
    }


def read_product(connection: Connection, product_id: int):
    return connection.execute(
        text("""
            SELECT stock, cost_price
            FROM products
            WHERE id = :product_id
        """),
        {"product_id": product_id},
    ).mappings().one()


def read_movements(connection: Connection, product_id: int):
    return connection.execute(
        text("""
            SELECT id, type, quantity_change, stock_after,
                   ref_id, operation_key
            FROM stock_movements
            WHERE product_id = :product_id
            ORDER BY id
        """),
        {"product_id": product_id},
    ).mappings().all()


def count_receipts(connection: Connection, supplier_id: int):
    return connection.execute(
        text("""
            SELECT COUNT(*)
            FROM import_receipts
            WHERE supplier_id = :supplier_id
        """),
        {"supplier_id": supplier_id},
    ).scalar_one()


@pytest.fixture
def rollback_env(test_db: Connection):
    """Savepoint-backed tests: no committed test records survive."""
    assert test_db.execute(
        text("SELECT DATABASE()")
    ).scalar_one() == "phone_shop_test"

    def factory():
        return Session(
            bind=test_db,
            join_transaction_mode="create_savepoint",
        )

    auth = AuthService(session_factory=factory)
    email = f"t41_rollback_{token_hex(8)}@example.test"

    user = auth.register(
        email=email,
        password=PASSWORD,
        confirm_password=PASSWORD,
        full_name="Task41 Rollback Admin",
        phone="0912345678",
    )

    test_db.execute(
        text("UPDATE users SET role = 'ADMIN' WHERE id = :id"),
        {"id": user.user_id},
    )

    store = Store()
    auth.login(
        email=email,
        password=PASSWORD,
        session_store=store,
    )

    with factory() as session, session.begin():
        brand_id = BrandRepository(session).create(
            name=f"T41 Brand {token_hex(7)}",
            now_utc=DB_NOW,
        )
        supplier_id = SupplierRepository(session).create(
            name=f"T41 Supplier {token_hex(7)}",
        )

        products = [
            ProductRepository(session).create(
                sku=f"T41-{token_hex(7)}",
                name=f"T41 Phone {i} {token_hex(5)}",
                brand_id=brand_id,
                storage="128GB",
                color="Black",
                sell_price=Decimal("1000000.00"),
                now_utc=DB_NOW,
            )
            for i in range(2)
        ]

    return {
        "db": test_db,
        "factory": factory,
        "auth": auth,
        "store": store,
        "supplier": supplier_id,
        "products": products,
    }


def rollback_service(env, **kwargs):
    return ImportService(
        session_factory=env["factory"],
        auth_service=env["auth"],
        clock=FixedClock(NOW),
        **kwargs,
    )


def rollback_import(env, lines, *, service=None):
    service = service or rollback_service(env)
    return service.create_import(
        session_store=env["store"],
        supplier_id=env["supplier"],
        items=lines,
    )


def test_half_up_is_persisted_in_mariadb(rollback_env):
    env = rollback_env
    product_id = env["products"][0]

    rollback_import(env, [item(product_id, 1, "0.01")])
    rollback_import(env, [item(product_id, 1, "0.02")])

    saved = read_product(env["db"], product_id)

    # (0.01 + 0.02) / 2 = 0.015 -> HALF_UP = 0.02
    assert saved["stock"] == 2
    assert saved["cost_price"] == Decimal("0.02")

    moves = read_movements(env["db"], product_id)
    assert len(moves) == 2
    assert [row["stock_after"] for row in moves] == [1, 2]


def test_each_receipt_item_has_exactly_one_import_movement(rollback_env):
    env = rollback_env
    a, b = env["products"]

    receipt = rollback_import(
        env,
        [
            item(b, 3, "200.00"),
            item(a, 2, "100.00"),
        ],
    )

    for product_id, quantity in ((a, 2), (b, 3)):
        movements = read_movements(env["db"], product_id)

        assert len(movements) == 1
        assert movements[0]["type"] == "IMPORT"
        assert movements[0]["quantity_change"] == quantity
        assert movements[0]["stock_after"] == quantity
        assert movements[0]["ref_id"] == receipt["id"]
        assert movements[0]["operation_key"] == (
            f"IMPORT:{receipt['id']}:{product_id}"
        )


def test_failure_on_second_movement_rolls_back_all_products(rollback_env):
    env = rollback_env
    a, b = env["products"]

    class FailSecondMovement(StockMovementRepository):
        def __init__(self, session):
            super().__init__(session)
            self.calls = 0

        def record_import(self, **kwargs):
            movement_id = super().record_import(**kwargs)
            self.calls += 1

            if self.calls == 2:
                raise RuntimeError("fail after second movement")

            return movement_id

    broken = rollback_service(
        env,
        movement_repository_factory=FailSecondMovement,
    )

    before = count_receipts(env["db"], env["supplier"])

    with pytest.raises(
        RuntimeError,
        match="fail after second movement",
    ):
        rollback_import(
            env,
            [
                item(a, 2, "100.00"),
                item(b, 3, "200.00"),
            ],
            service=broken,
        )

    assert count_receipts(env["db"], env["supplier"]) == before

    for product_id in (a, b):
        saved = read_product(env["db"], product_id)
        assert saved["stock"] == 0
        assert saved["cost_price"] == Decimal("0.00")
        assert read_movements(env["db"], product_id) == []

    item_count = env["db"].execute(
        text("""
            SELECT COUNT(*)
            FROM import_items
            WHERE product_id IN (:a, :b)
        """),
        {"a": a, "b": b},
    ).scalar_one()

    assert item_count == 0


def test_failure_after_receipt_insert_rolls_back_header(rollback_env):
    env = rollback_env
    product_id = env["products"][0]

    class FailCodeRepository(ImportRepository):
        def update_code(self, *, receipt_id, code):
            raise RuntimeError("fail while updating receipt code")

    broken = rollback_service(
        env,
        import_repository_factory=FailCodeRepository,
    )

    before = count_receipts(env["db"], env["supplier"])

    with pytest.raises(
        RuntimeError,
        match="fail while updating receipt code",
    ):
        rollback_import(
            env,
            [item(product_id, 1, "100.00")],
            service=broken,
        )

    assert count_receipts(env["db"], env["supplier"]) == before
    assert read_product(env["db"], product_id)["stock"] == 0
    assert read_movements(env["db"], product_id) == []


def test_duplicate_operation_key_is_rejected_by_unique(rollback_env):
    env = rollback_env
    product_id = env["products"][0]

    receipt = rollback_import(
        env,
        [item(product_id, 1, "100.00")],
    )

    with (
        env["factory"]() as session,
        session.begin(),
        pytest.raises(IntegrityError),
        session.begin_nested(),
    ):
        StockMovementRepository(session).record_import(
            receipt_id=receipt["id"],
            product_id=product_id,
            quantity=1,
            stock_after=2,
            created_at=NOW,
            created_by=env["auth"].require_user(session_store=env["store"]).user_id,
        )

    movements = read_movements(env["db"], product_id)
    assert len(movements) == 1
    assert movements[0]["stock_after"] == 1


@pytest.mark.parametrize(
    "invalid_sql",
    [
        "UPDATE products SET stock = -1 WHERE id = :id",
        (
            "UPDATE stock_movements SET quantity_change = 0 "
            "WHERE product_id = :id"
        ),
        (
            "UPDATE stock_movements SET stock_after = -1 "
            "WHERE product_id = :id"
        ),
    ],
)
def test_mariadb_check_constraints_block_invalid_stock(
    rollback_env, invalid_sql
):
    env = rollback_env
    product_id = env["products"][0]

    rollback_import(
        env,
        [item(product_id, 1, "100.00")],
    )

    with pytest.raises(DBAPIError), env["db"].begin_nested():
        env["db"].execute(
            text(invalid_sql),
            {"id": product_id},
        )

    assert read_product(env["db"], product_id)["stock"] == 1

    movements = read_movements(env["db"], product_id)
    assert len(movements) == 1
    assert movements[0]["quantity_change"] == 1
    assert movements[0]["stock_after"] == 1


# Real concurrency below uses separate DB connections and committed
# temporary records, unlike the single-connection rollback_env fixture.

@pytest.fixture
def live_env(test_db_engine: Engine):
    engine = test_db_engine

    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT DATABASE()")
        ).scalar_one() == "phone_shop_test"

    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    auth = AuthService(session_factory=factory)
    marker = token_hex(8)

    created = {
        "users": [],
        "brand": None,
        "suppliers": [],
        "products": [],
    }

    try:
        people = []

        for index in range(2):
            email = f"t41_live_{marker}_{index}@example.test"
            user = auth.register(
                email=email,
                password=PASSWORD,
                confirm_password=PASSWORD,
                full_name=f"Task41 Concurrent Admin {index}",
                phone="0912345678",
            )
            created["users"].append(user.user_id)
            people.append({
                "id": user.user_id,
                "email": email,
                "store": Store(),
            })

        with engine.begin() as connection:
            for user_id in created["users"]:
                connection.execute(
                    text("""
                        UPDATE users
                        SET role = 'ADMIN'
                        WHERE id = :user_id
                    """),
                    {"user_id": user_id},
                )

        for person in people:
            auth.login(
                email=person["email"],
                password=PASSWORD,
                session_store=person["store"],
            )

        with factory() as session, session.begin():
            brand_id = BrandRepository(session).create(
                name=f"T41 Live Brand {marker}",
                now_utc=DB_NOW,
            )
            created["brand"] = brand_id

            for index in range(2):
                supplier_id = SupplierRepository(session).create(
                    name=f"T41 Live Supplier {marker}-{index}",
                )
                created["suppliers"].append(supplier_id)

            for index in range(2):
                product_id = ProductRepository(session).create(
                    sku=f"T41LIVE-{marker}-{index}",
                    name=f"T41 Live Phone {marker}-{index}",
                    brand_id=brand_id,
                    storage="128GB",
                    color="Black",
                    sell_price=Decimal("1000000.00"),
                    now_utc=DB_NOW,
                )
                created["products"].append(product_id)

        yield {
            "engine": engine,
            "factory": factory,
            "auth": auth,
            "people": people,
            "suppliers": created["suppliers"],
            "products": created["products"],
        }

    finally:
        # Safe cleanup: only generated IDs, only phone_shop_test.
        # This cannot replace a transaction rollback if the test
        # process is forcibly terminated midway.
        with engine.begin() as connection:
            assert connection.execute(
                text("SELECT DATABASE()")
            ).scalar_one() == "phone_shop_test"

            db_user = connection.execute(
                text("SELECT CURRENT_USER()")
            ).scalar_one().split("@", 1)[0]

            assert db_user == "phone_shop_tester"

            for product_id in created["products"]:
                connection.execute(
                    text("""
                        DELETE FROM stock_movements
                        WHERE product_id = :product_id
                    """),
                    {"product_id": product_id},
                )

            for supplier_id in created["suppliers"]:
                connection.execute(
                    text("""
                        DELETE FROM import_items
                        WHERE receipt_id IN (
                            SELECT id
                            FROM import_receipts
                            WHERE supplier_id = :supplier_id
                        )
                    """),
                    {"supplier_id": supplier_id},
                )

                connection.execute(
                    text("""
                        DELETE FROM import_receipts
                        WHERE supplier_id = :supplier_id
                    """),
                    {"supplier_id": supplier_id},
                )

            for product_id in created["products"]:
                connection.execute(
                    text("DELETE FROM products WHERE id = :id"),
                    {"id": product_id},
                )

            for supplier_id in created["suppliers"]:
                connection.execute(
                    text("DELETE FROM suppliers WHERE id = :id"),
                    {"id": supplier_id},
                )

            if created["brand"] is not None:
                connection.execute(
                    text("DELETE FROM brands WHERE id = :id"),
                    {"id": created["brand"]},
                )

            for user_id in created["users"]:
                connection.execute(
                    text("DELETE FROM users WHERE id = :id"),
                    {"id": user_id},
                )


def live_service(env, **kwargs):
    return ImportService(
        session_factory=env["factory"],
        auth_service=env["auth"],
        clock=FixedClock(NOW),
        **kwargs,
    )


def live_import(env, actor_index, lines, *, service=None):
    return (service or live_service(env)).create_import(
        session_store=env["people"][actor_index]["store"],
        supplier_id=env["suppliers"][actor_index],
        items=lines,
    )


def test_two_admins_import_same_product_concurrently(live_env):
    env = live_env
    product_id = env["products"][0]
    start = Barrier(2)

    def worker(index):
        start.wait(timeout=10)
        return live_import(
            env,
            index,
            [
                item(
                    product_id,
                    quantity=2 if index == 0 else 3,
                    price="100.00" if index == 0 else "200.00",
                )
            ],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(worker, index)
            for index in range(2)
        ]
        results = [future.result(timeout=30) for future in futures]

    with env["engine"].connect() as connection:
        saved = read_product(connection, product_id)
        movements = read_movements(connection, product_id)

    assert saved["stock"] == 5
    assert saved["cost_price"] == Decimal("160.00")

    assert len(movements) == 2
    assert sum(row["quantity_change"] for row in movements) == 5
    assert {row["stock_after"] for row in movements} in (
        {2, 5},
        {3, 5},
    )

    assert len({row["id"] for row in results}) == 2
    assert len({row["code"] for row in results}) == 2

    keys = {row["operation_key"] for row in movements}
    assert keys == {
        f"IMPORT:{result['id']}:{product_id}"
        for result in results
    }


def test_reverse_product_order_uses_ascending_locks(live_env):
    env = live_env
    a, b = env["products"]
    start = Barrier(2)
    mutex = Lock()
    lock_calls = {}

    class AuditedInventory(InventoryRepository):
        def get_for_update(self, product_id):
            with mutex:
                lock_calls.setdefault(get_ident(), []).append(
                    product_id
                )
            return super().get_for_update(product_id)

    def worker(index):
        start.wait(timeout=10)
        lines = (
            [item(b, 1, "10.00"), item(a, 1, "10.00")]
            if index == 0
            else [item(a, 1, "20.00"), item(b, 1, "20.00")]
        )
        service = live_service(
            env,
            inventory_repository_factory=AuditedInventory,
        )
        return live_import(env, index, lines, service=service)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(worker, index)
            for index in range(2)
        ]
        results = [future.result(timeout=30) for future in futures]

    assert len(results) == 2
    assert len(lock_calls) == 2
    assert all(
        ids == sorted((a, b))
        for ids in lock_calls.values()
    )

    with env["engine"].connect() as connection:
        for product_id in (a, b):
            saved = read_product(connection, product_id)
            movements = read_movements(connection, product_id)

            assert saved["stock"] == 2
            assert saved["cost_price"] == Decimal("15.00")
            assert len(movements) == 2
            assert {row["stock_after"] for row in movements} == {1, 2}


def test_external_product_lock_blocks_import_until_release(live_env):
    env = live_env
    product_id = env["products"][0]
    about_to_lock = Event()

    class SignalingInventory(InventoryRepository):
        def get_for_update(self, requested_id):
            about_to_lock.set()
            return super().get_for_update(requested_id)

    service = live_service(
        env,
        inventory_repository_factory=SignalingInventory,
    )

    with env["engine"].connect() as holder:
        transaction = holder.begin()

        holder.execute(
            text("""
                SELECT id
                FROM products
                WHERE id = :product_id
                FOR UPDATE
            """),
            {"product_id": product_id},
        ).one()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                live_import,
                env,
                0,
                [item(product_id, 2, "100.00")],
                service=service,
            )

            try:
                assert about_to_lock.wait(timeout=10)

                # Worker has reached its FOR UPDATE statement,
                # but another connection still holds the row lock.
                sleep(0.2)
                assert not future.done()

            finally:
                if transaction.is_active:
                    transaction.rollback()

            result = future.result(timeout=30)

    assert result["code"] == f"PN{result['id']:08d}"

    with env["engine"].connect() as connection:
        saved = read_product(connection, product_id)
        movements = read_movements(connection, product_id)

    assert saved["stock"] == 2
    assert saved["cost_price"] == Decimal("100.00")
    assert len(movements) == 1
    assert movements[0]["stock_after"] == 2
