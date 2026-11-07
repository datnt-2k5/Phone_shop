
from datetime import UTC, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


class Clock(Protocol):
    def now_utc(self) -> datetime:
        ...


class SystemClock:
    def now_utc(self) -> datetime:
        return datetime.now(
            UTC
        ).replace(tzinfo=None)


class FixedClock:
    def __init__(self, fixed_time: datetime):
        self.set_time(fixed_time)

    def set_time(self, fixed_time: datetime):
        if (
            fixed_time.tzinfo is None
            or fixed_time.utcoffset() is None
        ):
            raise ValueError(
                "fixed_time phải có múi giờ"
            )

        self._time = fixed_time.astimezone(
            UTC
        ).replace(tzinfo=None)

    def now_utc(self) -> datetime:
        return self._time


def utc_to_vn(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)

    return dt.astimezone(VN_TZ)
