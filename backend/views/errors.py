class AppError(Exception):
    def __init__(self, message: str, code: int, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class AuthError(AppError):
    def __init__(self, message: str = "Unauthorized", code: int = 40101) -> None:
        super().__init__(message, code, status_code=401)


class RateLimitError(AppError):
    def __init__(self, message: str = "Rate limited", code: int = 42901) -> None:
        super().__init__(message, code, status_code=429)


class ValidationError(AppError):
    def __init__(self, message: str = "Validation failed", code: int = 42201) -> None:
        super().__init__(message, code, status_code=422)


class DomainError(AppError):
    def __init__(self, message: str = "Domain error", code: int = 40001) -> None:
        super().__init__(message, code, status_code=400)


class SystemError(AppError):
    def __init__(self, message: str = "System error", code: int = 50001) -> None:
        super().__init__(message, code, status_code=500)


class ForbiddenError(AppError):
    def __init__(self, message: str = "Forbidden", code: int = 40301) -> None:
        super().__init__(message, code, status_code=403)
