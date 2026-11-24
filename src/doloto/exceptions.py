from __future__ import annotations

import collections
import typing as t

from izulu import root


if t.TYPE_CHECKING:
    from collections import abc as cabc

    from doloto import core


class BaseDolotoExc(root.Error):
    __template__ = "doloto error"


class EmptyValueExc(BaseDolotoExc):
    __template__ = "Empty value: {label}"
    label: str

    @classmethod
    def validate(cls, values: cabc.Sized, *, label: str) -> None:
        if not values:
            raise cls(label=label)


# ---------------------------------------------------------------------------
# Schema specs
# ---------------------------------------------------------------------------


class BaseSchemaSpecExc(BaseDolotoExc):
    __template__ = "schema spec error"


class SchemaSpecDuplicateColumnsExc(BaseSchemaSpecExc):
    __template__ = "duplicate columns in schema spec: {duplicates}"
    columns: tuple[core.ColumnSpec, ...]

    def _duplicated_names(self) -> tuple[str, ...]:
        counts = collections.Counter(column.name for column in self.columns)
        return tuple(name for name, count in counts.items() if count > 1)

    duplicates: tuple[str, ...] = root.factory(
        default_factory=_duplicated_names,
        self=True,
    )


class SchemaSpecEmptyExc(BaseSchemaSpecExc):
    __template__ = "empty schema spec"


class SchemaSpecDiffEmptyExc(BaseSchemaSpecExc):
    __template__ = "empty schema spec diff"


class SchemaSpecMissingColumnExc(BaseSchemaSpecExc):
    __template__ = "no column {name!r} in schema spec"
    name: str


class SchemaSpecMissingPrimaryKeyExc(BaseSchemaSpecExc):
    __template__ = "no primary key in schema spec {name!r}"
    name: str


class SchemaSpecNullablePrimaryKeyExc(BaseSchemaSpecExc):
    __template__ = "primary key column {column!r} is nullable in schema spec {name!r}"
    name: str
    column: str


class SchemaSpecUnknownPrimaryKeyColumnExc(BaseSchemaSpecExc):
    __template__ = "primary key column {column!r} is not in schema spec {name!r}"
    name: str
    column: str


class CantRepresentColumnSpecExc(BaseDolotoExc):
    __template__ = (
        "column spec {name!r} of type={type!r} is"
        " not representable in backend={backend!r}"
    )
    name: str
    type: core.ColumnDataType
    backend: str
    reason: str = ""

    def _override_message(
        self,
        store: t.Any,
        kwargs: dict[str, t.Any],
        msg: str,
    ) -> str:
        if self.reason:
            return f"{msg} — {self.reason}"
        return msg


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class BaseDataTypeExc(BaseDolotoExc):
    __template__ = "data type error"


class DataTypeUnsupportedVarcharExc(BaseDataTypeExc):
    __template__ = "unsupported varchar({char_length})"
    char_length: int


class DataTypeUnsupportedDecimalExc(BaseDataTypeExc):
    __template__ = "unsupported decimal({precision},{scale})"
    precision: int
    scale: int


class DataTypeUnsupportedTimestampExc(BaseDataTypeExc):
    __template__ = "unsupported timestamp({unit}, tz_key={tz_key})"
    unit: str
    tz_key: str | None


class DataTypeUnsupportedUuidExc(BaseDataTypeExc):
    __template__ = "unsupported uuid(v{version})"
    version: int
