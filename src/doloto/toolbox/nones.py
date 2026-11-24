from collections import abc as cabc


class factory[T]:
    __slots__ = ("func",)

    def __init__(self, func: cabc.Callable[[], T]) -> None:
        self.func = func


def coalesce[T](value: T | factory[T], *values: T | factory[T]) -> T | None:
    for candidate in (value, *values):
        if isinstance(candidate, factory):
            candidate = candidate.func()
        if candidate is not None:
            return candidate
    return None
