
"""US04 Task 22: ma trận quyền theo Task.md mục 4.2.

N: từ chối; Y: cho phép; OWN: dữ liệu của mình; ALL: dữ liệu quản trị.
"""

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType


class Role(StrEnum):
    GUEST = "GUEST"
    CUSTOMER = "CUSTOMER"
    ADMIN = "ADMIN"
    SUPER_ADMIN = "SUPER_ADMIN"


class Access(StrEnum):
    DENY = "N"
    ALLOW = "Y"
    OWN = "OWN"
    ALL = "ALL"


class Permission(StrEnum):
    VIEW_PRODUCTS = "VIEW_PRODUCTS"
    REGISTER = "REGISTER"
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    VIEW_PROFILE = "VIEW_PROFILE"
    EDIT_PROFILE = "EDIT_PROFILE"
    PLACE_ORDER = "PLACE_ORDER"
    VIEW_ORDERS = "VIEW_ORDERS"
    CANCEL_ORDER = "CANCEL_ORDER"
    VIEW_INVOICES = "VIEW_INVOICES"
    MANAGE_PRODUCTS = "MANAGE_PRODUCTS"
    MANAGE_BRANDS = "MANAGE_BRANDS"
    MANAGE_SUPPLIERS = "MANAGE_SUPPLIERS"
    IMPORT_STOCK = "IMPORT_STOCK"
    VIEW_INVENTORY = "VIEW_INVENTORY"
    CONFIRM_ORDER = "CONFIRM_ORDER"
    COMPLETE_ORDER = "COMPLETE_ORDER"
    VIEW_CUSTOMERS = "VIEW_CUSTOMERS"
    VIEW_STATISTICS = "VIEW_STATISTICS"
    MANAGE_ACCOUNTS = "MANAGE_ACCOUNTS"
    LOCK_UNLOCK_ACCOUNTS = "LOCK_UNLOCK_ACCOUNTS"
    CHANGE_ROLE = "CHANGE_ROLE"
    MANAGE_SETTINGS = "MANAGE_SETTINGS"


_ROLE_ORDER = (
    Role.GUEST,
    Role.CUSTOMER,
    Role.ADMIN,
    Role.SUPER_ADMIN,
)

# Thứ tự: Guest, Customer, Admin, Super Admin.
_RULES: dict[
    Permission,
    tuple[Access, Access, Access, Access],
] = {
    Permission.VIEW_PRODUCTS: (
        Access.ALLOW, Access.ALLOW, Access.ALLOW, Access.ALLOW
    ),
    Permission.REGISTER: (
        Access.ALLOW, Access.DENY, Access.DENY, Access.DENY
    ),
    Permission.LOGIN: (
        Access.ALLOW, Access.DENY, Access.DENY, Access.DENY
    ),
    Permission.LOGOUT: (
        Access.DENY, Access.ALLOW, Access.ALLOW, Access.ALLOW
    ),
    Permission.VIEW_PROFILE: (
        Access.DENY, Access.OWN, Access.OWN, Access.OWN
    ),
    Permission.EDIT_PROFILE: (
        Access.DENY, Access.OWN, Access.OWN, Access.OWN
    ),
    Permission.PLACE_ORDER: (
        Access.DENY, Access.ALLOW, Access.DENY, Access.DENY
    ),
    Permission.VIEW_ORDERS: (
        Access.DENY, Access.OWN, Access.ALL, Access.ALL
    ),
    Permission.CANCEL_ORDER: (
        Access.DENY, Access.OWN, Access.ALL, Access.ALL
    ),
    Permission.VIEW_INVOICES: (
        Access.DENY, Access.OWN, Access.ALL, Access.ALL
    ),
    Permission.MANAGE_PRODUCTS: (
        Access.DENY, Access.DENY, Access.ALLOW, Access.ALLOW
    ),
    Permission.MANAGE_BRANDS: (
        Access.DENY, Access.DENY, Access.ALLOW, Access.ALLOW
    ),
    Permission.MANAGE_SUPPLIERS: (
        Access.DENY, Access.DENY, Access.ALLOW, Access.ALLOW
    ),
    Permission.IMPORT_STOCK: (
        Access.DENY, Access.DENY, Access.ALLOW, Access.ALLOW
    ),
    Permission.VIEW_INVENTORY: (
        Access.DENY, Access.DENY, Access.ALLOW, Access.ALLOW
    ),
    Permission.CONFIRM_ORDER: (
        Access.DENY, Access.DENY, Access.ALLOW, Access.ALLOW
    ),
    Permission.COMPLETE_ORDER: (
        Access.DENY, Access.DENY, Access.ALLOW, Access.ALLOW
    ),
    Permission.VIEW_CUSTOMERS: (
        Access.DENY, Access.DENY, Access.ALLOW, Access.ALLOW
    ),
    Permission.VIEW_STATISTICS: (
        Access.DENY, Access.DENY, Access.ALLOW, Access.ALLOW
    ),
    Permission.MANAGE_ACCOUNTS: (
        Access.DENY, Access.DENY, Access.DENY, Access.ALLOW
    ),
    Permission.LOCK_UNLOCK_ACCOUNTS: (
        Access.DENY, Access.DENY, Access.DENY, Access.ALLOW
    ),
    Permission.CHANGE_ROLE: (
        Access.DENY, Access.DENY, Access.DENY, Access.ALLOW
    ),
    Permission.MANAGE_SETTINGS: (
        Access.DENY, Access.DENY, Access.DENY, Access.ALLOW
    ),
}

# Chống các module khác vô tình chỉnh sửa ma trận.
PERMISSION_MATRIX: Mapping[
    Permission,
    Mapping[Role, Access],
] = MappingProxyType(
    {
        permission: MappingProxyType(
            dict(zip(_ROLE_ORDER, scopes, strict=True))
        )
        for permission, scopes in _RULES.items()
    }
)
