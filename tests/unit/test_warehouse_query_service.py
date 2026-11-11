
"""Task 39: permissions, validation, query delegation and read-only SQL."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from models.app_error import AppError
from repositories.warehouse_query_repository import WarehouseQueryRepository
from services.permissions import Permission
from services.warehouse_query_service import WarehouseQueryService


class FakeGuard:
    def __init__(self):
        self.permissions = []
        self.deny = False

    def run_allowed(self, *, session_store, permission, action):
        self.permissions.append(permission)
        if self.deny:
            raise AppError("FORBIDDEN", "Không có quyền.")
        return action(object())


class FakeRepository:
    def __init__(self):
        self.calls = []
        self.receipt = {"id": 7, "code": "PN00000007"}

    def list_receipts(self, **kwargs):
        self.calls.append(("list_receipts", kwargs))
        return [self.receipt]

    def get_receipt(self, receipt_id):
        self.calls.append(("get_receipt", receipt_id))
        return self.receipt

    def list_receipt_items(self, receipt_id):
        self.calls.append(("list_receipt_items", receipt_id))
        return [{"product_id": 4, "quantity": 2}]

    def list_movements(self, **kwargs):
        self.calls.append(("list_movements", kwargs))
        return [{"type": "IMPORT", "stock_after": 2}]

    def list_inventory(self, **kwargs):
        self.calls.append(("list_inventory", kwargs))
        return [{"id": 4, "stock_level": "LOW"}]


@pytest.fixture
def env():
    repo = FakeRepository()
    guard = FakeGuard()
    service = WarehouseQueryService(
        protected_actions=guard,
        repository_factory=lambda session: repo,
    )
    return SimpleNamespace(
        service=service,
        repo=repo,
        guard=guard,
        store=object(),
    )


def test_list_receipts_uses_view_inventory_permission(env):
    result = env.service.list_receipts(
        session_store=env.store, limit=10, offset=2
    )
    assert result[0]["code"] == "PN00000007"
    assert env.repo.calls == [
        ("list_receipts", {"limit": 10, "offset": 2})
    ]
    assert env.guard.permissions == [Permission.VIEW_INVENTORY]


def test_get_receipt_returns_header_and_details(env):
    result = env.service.get_receipt(
        session_store=env.store, receipt_id=7
    )
    assert result["receipt"]["id"] == 7
    assert result["items"] == [{"product_id": 4, "quantity": 2}]
    assert env.repo.calls == [
        ("get_receipt", 7),
        ("list_receipt_items", 7),
    ]


def test_missing_receipt_returns_not_found(env):
    env.repo.receipt = None
    with pytest.raises(AppError) as exc:
        env.service.get_receipt(
            session_store=env.store, receipt_id=999
        )
    assert exc.value.error_code == "NOT_FOUND"
    assert env.repo.calls == [("get_receipt", 999)]


def test_movement_filters_are_normalized(env):
    result = env.service.list_movements(
        session_store=env.store,
        product_id=4,
        movement_type=" import ",
        limit=5,
        offset=1,
    )
    assert result[0]["stock_after"] == 2
    assert env.repo.calls == [
        (
            "list_movements",
            {
                "product_id": 4,
                "movement_type": "IMPORT",
                "limit": 5,
                "offset": 1,
            },
        )
    ]


def test_inventory_filter_and_discontinued_flag(env):
    result = env.service.list_inventory(
        session_store=env.store,
        level=" low ",
        include_discontinued=True,
        limit=20,
        offset=0,
    )
    assert result[0]["stock_level"] == "LOW"
    assert env.repo.calls == [
        (
            "list_inventory",
            {
                "level": "LOW",
                "include_discontinued": True,
                "limit": 20,
                "offset": 0,
            },
        )
    ]


@pytest.mark.parametrize(
    "method",
    [
        "list_receipts",
        "get_receipt",
        "list_movements",
        "list_inventory",
    ],
)
def test_guard_denies_all_sensitive_read_methods(env, method):
    env.guard.deny = True
    kwargs = {"session_store": env.store}
    if method == "get_receipt":
        kwargs["receipt_id"] = 7

    with pytest.raises(AppError) as exc:
        getattr(env.service, method)(**kwargs)

    assert exc.value.error_code == "FORBIDDEN"
    assert env.repo.calls == []


@pytest.mark.parametrize(
    "limit,offset",
    [
        (0, 0),
        (101, 0),
        (True, 0),
        (2, -1),
        (2, "0"),
    ],
)
def test_invalid_pagination_fails_before_any_query(
    env, limit, offset
):
    with pytest.raises(AppError) as exc:
        env.service.list_receipts(
            session_store=env.store,
            limit=limit,
            offset=offset,
        )
    assert exc.value.error_code == "VALIDATION_ERROR"
    assert env.guard.permissions == []
    assert env.repo.calls == []


@pytest.mark.parametrize(
    "receipt_id",
    [0, -1, True, "7", None],
)
def test_invalid_receipt_id_fails_before_any_query(env, receipt_id):
    with pytest.raises(AppError) as exc:
        env.service.get_receipt(
            session_store=env.store,
            receipt_id=receipt_id,
        )
    assert exc.value.error_code == "VALIDATION_ERROR"
    assert env.guard.permissions == []


@pytest.mark.parametrize(
    "product_id",
    [0, -1, True, "7"],
)
def test_invalid_movement_product_id(env, product_id):
    with pytest.raises(AppError) as exc:
        env.service.list_movements(
            session_store=env.store,
            product_id=product_id,
        )
    assert exc.value.error_code == "VALIDATION_ERROR"
    assert env.guard.permissions == []


@pytest.mark.parametrize(
    "movement_type",
    ["DELETE", "", 123, True],
)
def test_invalid_movement_type_is_rejected(env, movement_type):
    with pytest.raises(AppError) as exc:
        env.service.list_movements(
            session_store=env.store,
            movement_type=movement_type,
        )
    assert exc.value.error_code == "VALIDATION_ERROR"
    assert env.guard.permissions == []


@pytest.mark.parametrize(
    "level",
    ["OVER", "", 1, None],
)
def test_invalid_inventory_level_is_rejected(env, level):
    with pytest.raises(AppError) as exc:
        env.service.list_inventory(
            session_store=env.store,
            level=level,
        )
    assert exc.value.error_code == "VALIDATION_ERROR"
    assert env.guard.permissions == []


@pytest.mark.parametrize(
    "value",
    [1, "false", None],
)
def test_invalid_discontinued_flag_is_rejected(env, value):
    with pytest.raises(AppError) as exc:
        env.service.list_inventory(
            session_store=env.store,
            include_discontinued=value,
        )
    assert exc.value.error_code == "VALIDATION_ERROR"
    assert env.guard.permissions == []


@pytest.mark.parametrize(
    "method,kwargs",
    [
        ("list_receipts", {"limit": 10, "offset": 0}),
        ("get_receipt", {"receipt_id": 1}),
        ("list_receipt_items", {"receipt_id": 1}),
        (
            "list_movements",
            {
                "product_id": 5,
                "movement_type": "IMPORT",
                "limit": 10,
                "offset": 0,
            },
        ),
        (
            "list_inventory",
            {
                "level": "ALERT",
                "include_discontinued": False,
                "limit": 10,
                "offset": 0,
            },
        ),
    ],
)
def test_repository_queries_are_read_only_and_parameterized(
    method, kwargs
):
    session = Mock()
    session.execute.return_value.mappings.return_value.all.return_value = []
    session.execute.return_value.mappings.return_value.first.return_value = None

    repo = WarehouseQueryRepository(session)
    getattr(repo, method)(**kwargs)

    sql, params = session.execute.call_args.args
    assert sql.text.lstrip().startswith("SELECT")

    upper = sql.text.upper()
    assert "UPDATE " not in upper
    assert "DELETE " not in upper
    assert "INSERT " not in upper

    assert ":limit" in upper.lower() or method in {
        "get_receipt",
        "list_receipt_items",
    }
    assert isinstance(params, dict)
