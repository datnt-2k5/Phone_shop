
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def _decimal(value):
    if isinstance(value, (float, bool)):
        raise TypeError(
            "Hãy dùng Decimal hoặc chuỗi thay cho float/bool"
        )

    return Decimal(value)


def quantize_money(value):
    return _decimal(value).quantize(
        CENT,
        rounding=ROUND_HALF_UP
    )


def weighted_average_cost(
    old_qty,
    old_cost,
    add_qty,
    add_cost
):
    if (
        type(old_qty) is not int
        or type(add_qty) is not int
    ):
        raise ValueError("Số lượng phải là số nguyên")

    if old_qty < 0 or add_qty <= 0:
        raise ValueError("Số lượng không hợp lệ")

    old_cost = _decimal(old_cost)
    add_cost = _decimal(add_cost)

    if old_cost < 0 or add_cost <= 0:
        raise ValueError("Giá vốn không hợp lệ")

    if old_qty == 0:
        return quantize_money(add_cost)

    total_value = (
        Decimal(old_qty) * old_cost
        + Decimal(add_qty) * add_cost
    )

    total_qty = Decimal(old_qty + add_qty)

    return quantize_money(
        total_value / total_qty
    )
