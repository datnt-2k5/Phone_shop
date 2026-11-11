
"""Task 42: validation, ordering, zero-delta and movement contracts."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from models.app_error import AppError
from repositories.stock_adjustment_repository import StockAdjustmentRepository
from services.permissions import Permission
from services.stock_adjustment_service import StockAdjustmentService


class FakeGuard:
    def __init__(self):
        self.permission = None
        self.deny = False

    def run_allowed(self, *, session_store, permission, action):
        self.permission = permission
        if self.deny:
            raise AppError("FORBIDDEN", "Không có quyền.")
        return action(object())


class FakeAuth:
    def require_user(self, *, session_store):
        return SimpleNamespace(user_id=7)


class FakeInventory:
    def __init__(self):
        self.rows = {
            2: {
                "id": 2,
                "stock": 3,
                "cost_price": Decimal("80.00"),
                "status": "ACTIVE",
            },
            10: {
                "id": 10,
                "stock": 5,
                "cost_price": Decimal("100.00"),
                "status": "ACTIVE",
            },
            15: {
                "id": 15,
                "stock": 0,
                "cost_price": Decimal("50.00"),
                "status": "DISCONTINUED",
            },
        }
        self.locks = []
        self.updates = []

    def get_for_update(self, product_id):
        self.locks.append(product_id)
        row = self.rows.get(product_id)
        return dict(row) if row is not None else None

    def set_balance(self, **kwargs):
        self.updates.append(kwargs)
        row = self.rows[kwargs["product_id"]]
        row["stock"] = kwargs["stock"]
        row["cost_price"] = kwargs["cost_price"]
        return True


class FakeAdjustments:
    def __init__(self):
        self.headers = []
        self.codes = []
        self.items = []
        self.movements = []
        self.fail_code = False
        self.fail_movement = False

    def create_adjustment(self, **kwargs):
        self.headers.append(kwargs)
        return 21

    def update_code(self, *, adjustment_id, code):
        self.codes.append((adjustment_id, code))
        return not self.fail_code

    def create_item(self, **kwargs):
        self.items.append(kwargs)
        return len(self.items)

    def record_movement(self, **kwargs):
        self.movements.append(kwargs)
        if self.fail_movement:
            raise RuntimeError("simulate movement failure")
        return len(self.movements)


@pytest.fixture
def env():
    guard = FakeGuard()
    auth = FakeAuth()
    inventory = FakeInventory()
    adjustments = FakeAdjustments()

    service = StockAdjustmentService(
        auth_service=auth,
        protected_actions=guard,
        adjustment_repository_factory=lambda session: adjustments,
        inventory_repository_factory=lambda session: inventory,
    )

    return SimpleNamespace(
        service=service,
        auth=auth,
        guard=guard,
        inventory=inventory,
        adjustments=adjustments,
        store=object(),
    )


def counted(product_id, actual_quantity):
    return {
        "product_id": product_id,
        "actual_quantity": actual_quantity,
    }


_DEFAULT_ITEMS = object()


def submit(
    env,
    items=_DEFAULT_ITEMS,
    reason="Kiểm kê cuối ngày",
):
    if items is _DEFAULT_ITEMS:
        items = [counted(10, 8)]

    return env.service.create_adjustment(
        session_store=env.store,
        reason=reason,
        items=items,
    )


def test_adjustment_sorts_locks_and_records_only_nonzero_deltas(env):
    result = submit(
        env,
        [
            counted(10, 8),
            counted(15, 0),
            counted(2, 1),
        ],
    )

    assert result == {
        "created": True,
        "id": 21,
        "code": "ADJ00000021",
        "changed_items": 2,
    }
    assert env.guard.permission == Permission.IMPORT_STOCK
    assert env.inventory.locks == [2, 10, 15]
    assert env.adjustments.codes == [(21, "ADJ00000021")]
    assert len(env.adjustments.headers) == 1
    assert env.adjustments.headers[0]["created_by"] == 7

    assert [
        (row["product_id"], row["quantity_change"])
        for row in env.adjustments.items
    ] == [(2, -2), (10, 3)]

    assert [
        (row["product_id"], row["stock_after"])
        for row in env.adjustments.movements
    ] == [(2, 1), (10, 8)]


def test_all_zero_deltas_do_not_create_document(env):
    result = submit(
        env,
        [
            counted(10, 5),
            counted(2, 3),
            counted(15, 0),
        ],
    )

    assert result["created"] is False
    assert result["id"] is None
    assert result["changed_items"] == 0
    assert env.adjustments.headers == []
    assert env.adjustments.items == []
    assert env.adjustments.movements == []
    assert env.inventory.updates == []


def test_adjustment_to_zero_preserves_last_cost(env):
    submit(env, [counted(10, 0)])

    assert env.inventory.rows[10]["stock"] == 0
    assert env.inventory.rows[10]["cost_price"] == Decimal("100.00")
    assert env.adjustments.movements[0]["quantity_change"] == -5


def test_discontinued_product_can_be_physically_counted(env):
    result = submit(env, [counted(15, 2)])

    assert result["created"] is True
    assert env.inventory.rows[15]["stock"] == 2
    assert env.inventory.rows[15]["cost_price"] == Decimal("50.00")


def test_successful_adjustment_preserves_cost_in_all_updates(env):
    submit(env, [counted(2, 0), counted(10, 8)])

    assert [
        row["cost_price"] for row in env.inventory.updates
    ] == [Decimal("80.00"), Decimal("100.00")]


@pytest.mark.parametrize(
    "reason",
    [
        "",
        "   ",
        "X" * 256,
        None,
        123,
        True,
    ],
)
def test_invalid_reason_rejected_before_any_database_action(env, reason):
    with pytest.raises(AppError) as caught:
        submit(env, reason=reason)

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert env.guard.permission is None


@pytest.mark.parametrize(
    "items",
    [
        [],
        "bad",
        None,
        [None],
        [counted(0, 1)],
        [counted(-1, 1)],
        [counted(True, 1)],
        [counted(10, -1)],
        [counted(10, True)],
        [counted(10, 1.5)],
        [counted(10, "5")],
        [counted(10, 2_147_483_648)],
        [counted(10, 8), counted(10, 9)],
        [{"product_id": 10}],
        [{"actual_quantity": 5}],
    ],
)
def test_invalid_items_rejected_before_database_action(env, items):
    with pytest.raises(AppError) as caught:
        submit(env, items=items)

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert env.guard.permission is None
    assert env.adjustments.headers == []


def test_missing_product_does_not_create_header(env):
    with pytest.raises(AppError) as caught:
        submit(env, [counted(999, 2)])

    assert caught.value.error_code == "NOT_FOUND"
    assert env.adjustments.headers == []


def test_permission_denied_does_not_create_header(env):
    env.guard.deny = True

    with pytest.raises(AppError) as caught:
        submit(env)

    assert caught.value.error_code == "FORBIDDEN"
    assert env.inventory.locks == []
    assert env.adjustments.headers == []


def test_code_update_failure_raises_for_transaction_rollback(env):
    env.adjustments.fail_code = True

    with pytest.raises(RuntimeError, match="mã phiếu"):
        submit(env)

    assert len(env.adjustments.headers) == 1
    assert env.adjustments.items == []


def test_movement_failure_propagates_for_transaction_rollback(env):
    env.adjustments.fail_movement = True

    with pytest.raises(RuntimeError, match="movement failure"):
        submit(env)

    assert len(env.adjustments.headers) == 1


def test_repository_rejects_zero_movement_without_sql():
    session = Mock()
    repo = StockAdjustmentRepository(session)

    with pytest.raises(ValueError, match="bằng 0"):
        repo.record_movement(
            adjustment_id=1,
            product_id=2,
            quantity_change=0,
            stock_after=5,
            reason="Kiểm kê",
            created_by=7,
            created_at=None,
        )

    session.execute.assert_not_called()


def test_repository_operation_key_and_sign_are_correct():
    session = Mock()
    session.execute.return_value.lastrowid = 8
    repo = StockAdjustmentRepository(session)

    result = repo.record_movement(
        adjustment_id=4,
        product_id=9,
        quantity_change=-3,
        stock_after=2,
        reason="Thiếu hàng thực tế",
        created_by=7,
        created_at=None,
    )

    sql, params = session.execute.call_args.args

    assert result == 8
    assert "'ADJUST'" in sql.text
    assert params["quantity_change"] == -3
    assert params["stock_after"] == 2
    assert params["operation_key"] == "ADJUST:4:9"
    assert params["reason"] == "Thiếu hàng thực tế"

    session.commit.assert_not_called()
    session.rollback.assert_not_called()
