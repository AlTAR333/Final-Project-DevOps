"""Contract error type and JSON body. Raised by validation (Armand) and orders (Tristan).

Owner: Armand.
"""

from common.contract import ErrorCode


class ApiError(Exception):
    def __init__(self, status: int, code: ErrorCode, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def error_body(code: ErrorCode, message: str) -> dict:
    return {"error": {"code": str(code), "message": message}}
