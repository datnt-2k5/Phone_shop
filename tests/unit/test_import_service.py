
"""Task 38: import validation, authorization and ordered stock workflow."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from models.app_error import AppError
from services.import_service import ImportService
from services.permissions import Permission


class FakeGuard:
    permission = None
    deny = False

    def run_allowed(self, *, session_store, permission, action):
        self.permission = permission

        if self.deny:
            raise AppError("FORBIDDEN", "Denied")

        return action(object())


class FakeAuth:
    def require_user(self, *, session_store):
        return SimpleNamespace(user_id=7)


class FakeSupplier:
    def __init__(self):
        self.active = True
        self.locked = False

    def get_by_id(self, supplier_id, *, for_update=False):
        self.locked = for_update

        if supplier_id == 3:
            return {
                "id": 3,
                "is_active": self.active,
            }

        return None


class FakeInventory:
    def __init__(self):
        self.rows = {
            2: {
                "stock": 0,
                "cost_price": Decimal("0.00"),
                "status": "ACTIVE",
            },
            9: {
                "stock": 10,
                "cost_price": Decimal("5000000.00"),
                "status": "ACTIVE",
            },
        }

        self.locks = []
        self.updates = []

    def get_for_update(self, product_id):
        self.locks.append(product_id)
        row = self.rows.get(product_id)

        return dict(row) if row is not None else None

    def set_balance(self, **values):
        self.updates.append(values)

        self.rows[values["product_id"]]["stock"] = values["stock"]
        self.rows[values["product_id"]]["cost_price"] = values["cost_price"]

        return True


class FakeImports:
    def __init__(self):
        self.receipt = None
        self.code = None
        self.items = []

    def create_receipt(self, **values):
        self.receipt = values
        return 15

    def update_code(self, *, receipt_id, code):
        self.code = code
        return receipt_id == 15

    def create_item(self, **values):
        self.items.append(values)
        return len(self.items)


class FakeMovements:
    def __init__(self):
        self.moves = []

    def record_import(self, **values):
        self.moves.append(values)
        return len(self.moves)


@pytest.fixture
def env():
    guard = FakeGuard()
    auth = FakeAuth()
    supplier = FakeSupplier()
    inventory = FakeInventory()
    imports = FakeImports()
    movement = FakeMovements()

    service = ImportService(
        auth_service=auth,
        protected_actions=guard,
        import_repository_factory=lambda session: imports,
        inventory_repository_factory=lambda session: inventory,
        movement_repository_factory=lambda session: movement,
        supplier_repository_factory=lambda session: supplier,
    )

    return SimpleNamespace(
        service=service,
        guard=guard,
        supplier=supplier,
        inventory=inventory,
        imports=imports,
        movement=movement,
        store=object(),
    )


def line(
    product_id=9,
    quantity=5,
    import_price="5500000.00",
):
    return {
        "product_id": product_id,
        "quantity": quantity,
        "import_price": import_price,
    }


def submit(env, items=None, supplier_id=3, note=None):
    return env.service.create_import(
        session_store=env.store,
        supplier_id=supplier_id,
        items=items if items is not None else [line()],
        note=note,
    )


def test_full_workflow_locks_in_id_order_and_records_movements(env):
    result = submit(
        env,
        [
            line(9),
            line(2, 3, "100.00"),
        ],
        note="  Task 38  ",
    )

    assert result == {
        "id": 15,
        "code": "PN00000015",
        "total_amount": Decimal("27500300.00"),
    }

    assert env.guard.permission == Permission.IMPORT_STOCK
    assert env.supplier.locked is True

    # Dữ liệu đầu vào là 9, 2 nhưng thứ tự khóa phải là 2, 9.
    assert env.inventory.locks == [2, 9]

    assert [
        item["product_id"] for item in env.imports.items
    ] == [2, 9]

    assert env.imports.receipt["created_by"] == 7
    assert env.imports.receipt["note"] == "Task 38"
    assert env.imports.code == "PN00000015"

    assert [
        (
            m["product_id"],
            m["quantity"],
            m["stock_after"],
        )
        for m in env.movement.moves
    ] == [
        (2, 3, 3),
        (9, 5, 15),
    ]


def test_weighted_average_uses_decimal_half_up(env):
    submit(env)

    assert env.inventory.rows[9]["stock"] == 15
    assert env.inventory.rows[9]["cost_price"] == Decimal(
        "5166666.67"
    )


def test_zero_opening_stock_uses_import_price(env):
    submit(
        env,
        [line(2, 2, "123.45")],
    )

    assert env.inventory.rows[2]["cost_price"] == Decimal(
        "123.45"
    )


@pytest.mark.parametrize(
    "items",
    [
        [],
        "not a list",
        [None],
        [line(9, 0)],
        [line(9, -1)],
        [line(9, True)],
        [line(9, 2.5)],
        [line(9, 2, 1.2)],
        [line(9, 2, "0")],
        [line(9, 2, "1.234")],
        [line(9, 2, "NaN")],
        [line(9), line(9)],
        [line(True)],
        [
            {
                "quantity": 1,
                "import_price": "100.00",
            }
        ],
    ],
)
def test_invalid_items_are_rejected_before_write(env, items):
    with pytest.raises(AppError) as caught:
        submit(env, items)

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert env.imports.receipt is None
    assert env.inventory.locks == []


@pytest.mark.parametrize(
    "supplier_id",
    [0, -1, True, "3", None],
)
def test_invalid_supplier_id_is_rejected(env, supplier_id):
    with pytest.raises(AppError) as caught:
        submit(env, supplier_id=supplier_id)

    assert caught.value.error_code == "VALIDATION_ERROR"


def test_inactive_supplier_is_denied(env):
    env.supplier.active = False

    with pytest.raises(AppError) as caught:
        submit(env)

    assert caught.value.error_code == "SUPPLIER_INACTIVE"
    assert env.imports.receipt is None


def test_unknown_product_is_denied(env):
    with pytest.raises(AppError) as caught:
        submit(env, [line(999)])

    assert caught.value.error_code == "NOT_FOUND"
    assert env.imports.receipt is None


def test_discontinued_product_is_denied(env):
    env.inventory.rows[9]["status"] = "DISCONTINUED"

    with pytest.raises(AppError) as caught:
        submit(env)

    assert caught.value.error_code == "PRODUCT_INACTIVE"
    assert env.imports.receipt is None


def test_overflow_is_denied(env):
    env.inventory.rows[9]["stock"] = 2_147_483_647

    with pytest.raises(AppError) as caught:
        submit(env)

    assert caught.value.error_code == "STOCK_OVERFLOW"
    assert env.imports.receipt is None


def test_role_denied_before_any_write(env):
    env.guard.deny = True

    with pytest.raises(AppError) as caught:
        submit(env)

    assert caught.value.error_code == "FORBIDDEN"
    assert env.imports.receipt is None
    assert env.inventory.locks == []


def test_bad_note_is_rejected(env):
    with pytest.raises(AppError, match="Ghi chú"):
        submit(env, note="X" * 256)
