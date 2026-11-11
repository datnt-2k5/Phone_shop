
"""Task 43: protected adjustment-history queries and SQL projections."""

from unittest.mock import Mock

import pytest

from models.app_error import AppError
from repositories.stock_adjustment_repository import StockAdjustmentRepository
from services.permissions import Permission
from services.stock_adjustment_service import StockAdjustmentService


class FakeGuard:
    def __init__(self):
        self.permissions = []
        self.denied = False

    def run_allowed(
        self,
        *,
        permission,
        session_store,
        action,
    ):
        self.permissions.append(permission)

        if self.denied:
            raise AppError(
                "FORBIDDEN",
                "Không đủ quyền",
            )

        return action(object())


class FakeRepo:
    def list_adjustments(self, *, limit, offset):
        return [
            {
                "id": 8,
                "code": "ADJ00000008",
                "limit": limit,
                "offset": offset,
            }
        ]

    def get_adjustment(self, adjustment_id):
        if adjustment_id == 999:
            return None

        return {
            "id": adjustment_id,
            "code": "ADJ00000008",
        }

    def list_items(self, adjustment_id):
        return [
            {
                "adjustment_id": adjustment_id,
                "quantity_change": -2,
            }
        ]


@pytest.fixture
def env():
    guard = FakeGuard()
    repo = FakeRepo()

    service = StockAdjustmentService(
        auth_service=Mock(),
        protected_actions=guard,
        adjustment_repository_factory=lambda session: repo,
    )

    return service, guard, object()


def test_list_history_requires_view_inventory(env):
    service, guard, store = env

    data = service.list_adjustments(
        session_store=store,
        limit=11,
        offset=20,
    )

    assert data[0]["offset"] == 20
    assert guard.permissions == [
        Permission.VIEW_INVENTORY
    ]


def test_detail_requires_view_inventory(env):
    service, guard, store = env

    data = service.get_adjustment(
        session_store=store,
        adjustment_id=8,
    )

    assert data["adjustment"]["id"] == 8
    assert data["items"][0]["quantity_change"] == -2

    assert guard.permissions == [
        Permission.VIEW_INVENTORY
    ]


def test_missing_adjustment_is_not_found(env):
    service, _guard, store = env

    with pytest.raises(AppError) as caught:
        service.get_adjustment(
            session_store=store,
            adjustment_id=999,
        )

    assert caught.value.error_code == "NOT_FOUND"


def test_permission_denial_blocks_history(env):
    service, guard, store = env
    guard.denied = True

    with pytest.raises(AppError) as caught:
        service.list_adjustments(
            session_store=store,
        )

    assert caught.value.error_code == "FORBIDDEN"


@pytest.mark.parametrize(
    "limit,offset",
    [
        (0, 0),
        (101, 0),
        (True, 0),
        (10, -1),
    ],
)
def test_invalid_pagination_does_not_query(
    env,
    limit,
    offset,
):
    service, guard, store = env

    with pytest.raises(AppError) as caught:
        service.list_adjustments(
            session_store=store,
            limit=limit,
            offset=offset,
        )

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert guard.permissions == []


@pytest.mark.parametrize(
    "bad_id",
    [0, -1, True, "8", None],
)
def test_invalid_detail_id_does_not_query(env, bad_id):
    service, guard, store = env

    with pytest.raises(AppError) as caught:
        service.get_adjustment(
            session_store=store,
            adjustment_id=bad_id,
        )

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert guard.permissions == []


def test_repository_history_list_is_parameterized_and_readonly():
    session = Mock()

    (
        session.execute.return_value
        .mappings.return_value
        .all.return_value
    ) = [
        {
            "id": 2,
            "code": "ADJ00000002",
        }
    ]

    result = StockAdjustmentRepository(
        session
    ).list_adjustments(
        limit=11,
        offset=0,
    )

    sql, params = session.execute.call_args.args

    assert result[0]["id"] == 2
    assert "LIMIT :limit OFFSET :offset" in sql.text
    assert "ORDER BY a.id DESC" in sql.text
    assert params == {
        "limit": 11,
        "offset": 0,
    }

    assert sql.text.strip().upper().startswith("SELECT")
    session.commit.assert_not_called()


def test_repository_detail_items_join_product_names():
    session = Mock()

    (
        session.execute.return_value
        .mappings.return_value
        .all.return_value
    ) = [
        {
            "product_id": 3,
            "sku": "A-03",
            "product_name": "Máy A",
        }
    ]

    result = StockAdjustmentRepository(
        session
    ).list_items(7)

    sql, params = session.execute.call_args.args

    assert result[0]["sku"] == "A-03"
    assert "JOIN products" in sql.text
    assert params == {
        "adjustment_id": 7,
    }

    session.commit.assert_not_called()
