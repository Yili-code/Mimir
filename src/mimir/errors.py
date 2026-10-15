class MimirError(Exception):
    """Base error for expected Mimir failures."""


class ConfigurationError(MimirError):
    """Required runtime configuration is absent or invalid."""


class RetryableError(MimirError):
    """A transient boundary failure that a later workflow run may retry."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


class PermanentError(MimirError):
    """A bounded input or provider failure that retrying will not repair."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
