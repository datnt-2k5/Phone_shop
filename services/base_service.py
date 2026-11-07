
from datetime import datetime

from utils.time_utils import Clock, SystemClock


class BaseService:
    def __init__(
        self,
        clock: Clock | None = None
    ) -> None:
        self.clock = (
            clock
            if clock is not None
            else SystemClock()
        )

    def current_time(self) -> datetime:
        return self.clock.now_utc()
