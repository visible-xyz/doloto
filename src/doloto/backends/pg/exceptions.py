from __future__ import annotations

from doloto import exceptions as excs


class BasePgBackendExc(excs.BaseDolotoExc):
    __template__ = "pg backend error"


class BareNumericExc(BasePgBackendExc):
    __template__ = (
        "numeric column {name} needs explicit precision/scale"
        " — the source declares none"
    )
    name: str


class UnsupportedPgTypeExc(BasePgBackendExc):
    __template__ = "unsupported PG type {data_type} of column {name}"
    data_type: str
    name: str
