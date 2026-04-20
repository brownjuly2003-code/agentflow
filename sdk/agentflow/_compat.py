import warnings
from collections.abc import Callable
from functools import wraps
from typing import Any


def deprecated(
    replacement: str,
    removed_in: str,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            warnings.warn(
                (
                    f"{func.__name__} is deprecated and will be removed in {removed_in}. "
                    f"Use {replacement} instead."
                ),
                DeprecationWarning,
                stacklevel=2,
            )
            return func(*args, **kwargs)

        return wrapper

    return decorator
