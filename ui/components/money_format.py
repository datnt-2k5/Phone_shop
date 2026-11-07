"""Định dạng VND để HIỂN THỊ; không thay đổi giá trị tiền trong database."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


def format_vnd(value: Decimal | str | int) -> str:
    """Hiển thị tiền làm tròn đến đồng, ví dụ 12500000.5 -> '12.500.001 ₫'."""
    if isinstance(value, (float, bool)):
        raise TypeError("Tiền phải là Decimal, chuỗi hoặc số nguyên; không dùng float")

    try:
        money = Decimal(value)
        if not money.is_finite():
            raise ValueError("Số tiền phải hữu hạn")
        rounded = money.quantize(Decimal(1), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError("Giá trị tiền không hợp lệ") from exc

    return f"{rounded:,.0f}".replace(",", ".") + " ₫"
