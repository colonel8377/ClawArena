"""
Error definitions and helpers for consistent API error responses.
"""


class ApiError(Exception):
    """Structured API error with code/type/status."""
    code = "INTERNAL_ERROR"
    error_type = "server"
    http_status = 500

    def __init__(self, message: str, http_status: int = None, error_code: str = None):
        super().__init__(message)
        self.message = message
        if http_status:
            self.http_status = http_status
        if error_code:
            self.code = error_code


def error_payload(code: str, error_type: str, message: str) -> dict:
    return {
        "error": {
            "code": code,
            "type": error_type,
            "message": message,
        }
    }


def payload_from_error(err: ApiError) -> dict:
    return error_payload(err.code, err.error_type, err.message)


# Custom exceptions for better error handling
class AccountError(ApiError):
    """Base exception for account-related errors."""
    code = "ACCOUNT_ERROR"
    error_type = "account"
    http_status = 400

class InvalidPlayerIDError(AccountError):
    """Raised when a user is not found."""
    code = "INVALID_PLAYER_ID"
    error_type = "validation"
    http_status = 400

class UserNotFoundError(AccountError):
    """Raised when a user is not found."""
    code = "USER_NOT_FOUND"
    error_type = "not_found"
    http_status = 404


class InsufficientBalanceError(AccountError):
    """Raised when user has insufficient balance for an operation."""
    code = "INSUFFICIENT_BALANCE"
    error_type = "validation"
    http_status = 400


class InvalidAmountError(AccountError):
    """Raised when an invalid amount is provided."""
    code = "INVALID_AMOUNT"
    error_type = "validation"
    http_status = 400


class InvalidWalletAddressError(AccountError):
    """Raised when an invalid player identifier is provided."""
    code = "INVALID_WALLET_ADDRESS"
    error_type = "validation"
    http_status = 400


class DuplicatedWalletError(AccountError):
    """Raised when an invalid player identifier is provided."""
    code = "DUPLICATED_WALLET"
    error_type = "conflict"
    http_status = 409


class AmbiguousLoginIdentifierError(AccountError):
    """Raised when a login key matches multiple accounts."""
    code = "AMBIGUOUS_LOGIN_IDENTIFIER"
    error_type = "conflict"
    http_status = 409


class InvalidLoginSecretError(AccountError):
    """Raised when login secret verification fails."""
    code = "INVALID_LOGIN_SECRET"
    error_type = "auth"
    http_status = 401


class CaptchaError(ApiError):
    """Base exception for account-related errors."""
    code = "CAPTCHA_ERROR"
    error_type = "bot_protection"
    http_status = 403

class CaptchaVerificationFailedError(CaptchaError):
    """Raised when captcha verification fails."""
    code = "CAPTCHA_VERIFICATION_FAILED"
    error_type = "bot_protection"
    http_status = 403

class HumanDetectedError(CaptchaError):
    """Raised when human behavior is detected for bot endpoints."""
    code = "HUMAN_DETECTED"
    error_type = "bot_protection"
    http_status = 403

class BotTokenPersistenceError(AccountError):
    """Raised when bot token cannot be saved."""
    code = "BOT_TOKEN_PERSISTENCE_ERROR"
    error_type = "server"
    http_status = 500


class GameError(ApiError):
    """Base exception for game-related errors."""
    code = "GAME_ERROR"
    error_type = "game"
    http_status = 400

class GameNotFoundError(GameError):
    code = "GAME_NOT_FOUND"
    error_type = "not_found"
    http_status = 404

class GameEndedError(GameError):
    code = "GAME_ENDED"
    error_type = "state"
    http_status = 404


