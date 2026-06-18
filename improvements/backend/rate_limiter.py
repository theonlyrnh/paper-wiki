"""Global rate limiter for FastAPI using slowapi."""

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware


def get_limiter():
    """Create and configure the rate limiter."""
    return Limiter(
        key_func=get_remote_address,
        default_limits=["200/minute"],  # Global default
        storage_uri="memory://",
        headers_enabled=True,
    )


def setup_rate_limiting(app):
    """Setup rate limiting middleware and exception handler."""
    limiter = get_limiter()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    return limiter
