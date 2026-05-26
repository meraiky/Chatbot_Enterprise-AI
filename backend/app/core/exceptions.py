

class ChatbotException(Exception):
    """Base exception for all chatbot-related errors."""
    def __init__(self, message: str, status_code: int = 500, detail: str | None = None):
        self.message = message
        self.status_code = status_code
        self.detail = detail
        super().__init__(self.message)

class AuthenticationException(ChatbotException):
    """Raised when authentication fails."""
    def __init__(self, message: str = "Authentication failed", detail: str | None = None):
        super().__init__(message, status_code=401, detail=detail)

class AuthorizationException(ChatbotException):
    """Raised when a user lacks necessary permissions."""
    def __init__(self, message: str = "Permission denied", detail: str | None = None):
        super().__init__(message, status_code=403, detail=detail)

class ResourceNotFoundException(ChatbotException):
    """Raised when a requested resource is not found."""
    def __init__(self, resource: str, resource_id: str, detail: str | None = None):
        message = f"{resource} with id {resource_id} not found"
        super().__init__(message, status_code=404, detail=detail)

class ValidationException(ChatbotException):
    """Raised when input validation fails."""
    def __init__(self, message: str, detail: str | None = None):
        super().__init__(message, status_code=400, detail=detail)

class ExternalServiceException(ChatbotException):
    """Raised when an external service (LLM, Vector DB) fails."""
    def __init__(self, service: str, message: str, detail: str | None = None):
        full_message = f"External service error ({service}): {message}"
        super().__init__(full_message, status_code=502, detail=detail)

class RateLimitException(ChatbotException):
    """Raised when a request is rate limited."""
    def __init__(self, message: str = "Too many requests", detail: str | None = None):
        super().__init__(message, status_code=429, detail=detail)
