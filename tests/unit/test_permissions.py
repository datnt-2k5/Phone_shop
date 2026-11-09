
"""Task 22: đối chiếu ma trận với Task.md mục 4.2."""

import pytest

from services.permissions import PERMISSION_MATRIX, Access, Permission, Role

# Thứ tự bốn ký hiệu: Guest, Customer, Admin, Super Admin.
EXPECTED = {
    Permission.VIEW_PRODUCTS: ("Y", "Y", "Y", "Y"),
    Permission.REGISTER: ("Y", "N", "N", "N"),
    Permission.LOGIN: ("Y", "N", "N", "N"),
    Permission.LOGOUT: ("N", "Y", "Y", "Y"),
    Permission.VIEW_PROFILE: ("N", "OWN", "OWN", "OWN"),
    Permission.EDIT_PROFILE: ("N", "OWN", "OWN", "OWN"),
    Permission.PLACE_ORDER: ("N", "Y", "N", "N"),
    Permission.VIEW_ORDERS: ("N", "OWN", "ALL", "ALL"),
    Permission.CANCEL_ORDER: ("N", "OWN", "ALL", "ALL"),
    Permission.VIEW_INVOICES: ("N", "OWN", "ALL", "ALL"),
    Permission.MANAGE_PRODUCTS: ("N", "N", "Y", "Y"),
    Permission.MANAGE_BRANDS: ("N", "N", "Y", "Y"),
    Permission.MANAGE_SUPPLIERS: ("N", "N", "Y", "Y"),
    Permission.IMPORT_STOCK: ("N", "N", "Y", "Y"),
    Permission.VIEW_INVENTORY: ("N", "N", "Y", "Y"),
    Permission.CONFIRM_ORDER: ("N", "N", "Y", "Y"),
    Permission.COMPLETE_ORDER: ("N", "N", "Y", "Y"),
    Permission.VIEW_CUSTOMERS: ("N", "N", "Y", "Y"),
    Permission.VIEW_STATISTICS: ("N", "N", "Y", "Y"),
    Permission.MANAGE_ACCOUNTS: ("N", "N", "N", "Y"),
    Permission.LOCK_UNLOCK_ACCOUNTS: ("N", "N", "N", "Y"),
    Permission.CHANGE_ROLE: ("N", "N", "N", "Y"),
    Permission.MANAGE_SETTINGS: ("N", "N", "N", "Y"),
}


@pytest.mark.parametrize(
    ("permission", "expected"),
    list(EXPECTED.items()),
)
def test_matrix_matches_task_md(permission, expected):
    actual = tuple(
        PERMISSION_MATRIX[permission][role].value
        for role in Role
    )
    assert actual == expected


def test_matrix_is_complete():
    assert len(PERMISSION_MATRIX) == 23
    assert set(PERMISSION_MATRIX) == set(Permission)

    for roles in PERMISSION_MATRIX.values():
        assert set(roles) == set(Role)
        assert all(
            isinstance(value, Access)
            for value in roles.values()
        )


def test_matrix_is_read_only():
    with pytest.raises(TypeError):
        PERMISSION_MATRIX[Permission.VIEW_PRODUCTS] = {}

    with pytest.raises(TypeError):
        PERMISSION_MATRIX[
            Permission.VIEW_PRODUCTS
        ][Role.GUEST] = Access.DENY
