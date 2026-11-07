from typing import Any


class AppError(Exception):
    def __init__(
        self,
        error_code: str,
        message: str,
        errors: dict[str, Any] | None = None,
    ) -> None:
        self.error_code = error_code
        self.message = message
        self.errors = errors or {}

        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": self.message,
            "errors": self.errors,
        }
