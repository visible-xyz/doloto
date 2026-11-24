from __future__ import annotations

import typing as t

from doloto import exceptions as excs


if t.TYPE_CHECKING:
    from doloto import core


class BaseSqlFamilyExc(excs.BaseDolotoExc):
    __template__ = "sql family error"


class CantBuildCastExc(BaseSqlFamilyExc):
    __template__ = "cannot build a cast to {type!r} for column {name}"
    name: str
    type: core.ColumnDataType


class NoTablesRequestedExc(BaseSqlFamilyExc):
    __template__ = "no tables requested"


class TablesNotLoadableExc(BaseSqlFamilyExc):
    __template__ = "tables not loadable in schema {db_schema!r}: {problems}"
    db_schema: str
    problems: dict[str, tuple[str, ...]]
