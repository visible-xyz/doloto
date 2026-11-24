from __future__ import annotations

from collections import abc as cabc
import types
import typing as t

from sqlglot import expressions as exp

from doloto import datatypes
from doloto.families.sql import exceptions as excs
from doloto.families.sql import types as sql_types


if t.TYPE_CHECKING:
    from doloto import core


def _varchar_cast_type(column_type: datatypes.Varchar) -> exp.DataType:
    length = exp.DataTypeParam(this=exp.Literal.number(column_type.char_length))
    return exp.DataType(this=exp.DataType.Type.VARCHAR, expressions=[length])


def _decimal_cast_type(column_type: datatypes.Decimal) -> exp.DataType:
    precision = exp.DataTypeParam(this=exp.Literal.number(column_type.precision))
    scale = exp.DataTypeParam(this=exp.Literal.number(column_type.scale))
    return exp.DataType(this=exp.DataType.Type.DECIMAL, expressions=[precision, scale])


_CAST_TYPES: t.Final[
    types.MappingProxyType[
        sql_types.ColumnTypeKey,
        cabc.Callable[[t.Any], exp.DataType],
    ]
] = types.MappingProxyType(
    {
        datatypes.Scalars.INT16: lambda _: exp.DataType(
            this=exp.DataType.Type.SMALLINT,
        ),
        datatypes.Scalars.INT32: lambda _: exp.DataType(this=exp.DataType.Type.INT),
        datatypes.Scalars.INT64: lambda _: exp.DataType(this=exp.DataType.Type.BIGINT),
        datatypes.Scalars.FLOAT32: lambda _: exp.DataType(this=exp.DataType.Type.FLOAT),
        datatypes.Scalars.FLOAT64: lambda _: exp.DataType(
            this=exp.DataType.Type.DOUBLE,
        ),
        datatypes.Scalars.DATE: lambda _: exp.DataType(this=exp.DataType.Type.DATE),
        datatypes.Scalars.BOOL: lambda _: exp.DataType(this=exp.DataType.Type.BOOLEAN),
        datatypes.Scalars.TEXT: lambda _: exp.DataType(this=exp.DataType.Type.TEXT),
        datatypes.Varchar: _varchar_cast_type,
        datatypes.Decimal: _decimal_cast_type,
        datatypes.Timestamp: lambda column_type: exp.DataType(
            this=exp.DataType.Type.TIMESTAMP
            if column_type.is_naive
            else exp.DataType.Type.TIMESTAMPTZ,
        ),
    },
)


def _resolve_cast_type(name: str, column_type: core.ColumnDataType) -> exp.DataType:
    if isinstance(column_type, (datatypes.Scalars, datatypes.BackendScalars)):
        builder = _CAST_TYPES.get(column_type)
    else:
        builder = _CAST_TYPES.get(type(column_type))
    if builder is None:
        raise excs.CantBuildCastExc(name=name, type=column_type)
    return builder(column_type)


def _project_column(
    name: str,
    *,
    cast: core.ColumnDataType | None,
    alias: str | None,
    db_schema: str | None = None,
    table_name: str | None = None,
) -> exp.Expression:
    if not name:
        raise ValueError("empty column name")
    if alias is not None and not alias:
        raise ValueError(f"empty alias for column {name!r}")
    column = exp.column(name, table=table_name, db=db_schema)
    if cast:
        column = exp.cast(column, _resolve_cast_type(name, cast))
    if cast or alias:
        # a cast keeps the column under its own name unless an alias says otherwise
        return exp.alias_(column, alias or name)
    return column


def project(
    column_names: cabc.Iterable[str],
    *,
    casts: cabc.Mapping[str, core.ColumnDataType | None] | None = None,
    aliases: cabc.Mapping[str, str] | None = None,
    db_schema: str | None = None,
    table_name: str | None = None,
) -> tuple[exp.Expression, ...]:
    """Project the columns; `casts` and `aliases` are by source column, sparse."""
    casts = casts or {}
    aliases = aliases or {}
    return tuple(
        _project_column(
            name,
            cast=casts.get(name),
            alias=aliases.get(name),
            db_schema=db_schema,
            table_name=table_name,
        )
        for name in column_names
    )


def spec_select(
    schema_spec: core.SchemaSpec,
    *,
    db_schema: str,
    db_table: str | None = None,
) -> exp.Select:
    """The naive `SELECT <spec columns, in spec order> FROM <table>`."""
    table = exp.table_(db_table or schema_spec.name, db=db_schema)
    return exp.select(*project(schema_spec.get_column_names())).from_(table)
