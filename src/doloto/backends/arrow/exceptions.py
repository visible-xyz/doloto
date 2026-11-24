from __future__ import annotations

from doloto import exceptions as excs


class BaseArrowBackendExc(excs.BaseDolotoExc):
    __template__ = "arrow backend error"


class CharLengthExceededExc(BaseArrowBackendExc):
    __template__ = (
        "column {name} exceeds varchar({char_length}):"
        " longest value is {max_length} chars"
    )
    name: str
    char_length: int
    max_length: int
