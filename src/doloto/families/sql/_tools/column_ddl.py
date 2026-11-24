from __future__ import annotations

import typing as t

from sqlglot import expressions as exp

from doloto import datatypes
from doloto import exceptions as dl_excs
from doloto.families.sql import types as sql_types


if t.TYPE_CHECKING:
    from collections import abc as cabc

    from doloto import core


def render_smallint(_column_type: t.Any) -> str:
    return "SMALLINT"


def render_integer(_column_type: t.Any) -> str:
    return "INTEGER"


def render_bigint(_column_type: t.Any) -> str:
    return "BIGINT"


def render_real(_column_type: t.Any) -> str:
    return "REAL"


def render_double_precision(_column_type: t.Any) -> str:
    return "DOUBLE PRECISION"


def render_date(_column_type: t.Any) -> str:
    return "DATE"


def render_boolean(_column_type: t.Any) -> str:
    return "BOOLEAN"


def render_numeric(column_type: datatypes.Decimal) -> str:
    return f"NUMERIC({column_type.precision},{column_type.scale})"


def render_timestamp(column_type: datatypes.Timestamp) -> str:
    if column_type.unit != "us":  # microseconds
        raise dl_excs.DataTypeUnsupportedTimestampExc(
            unit=column_type.unit,
            tz_key=column_type.tz_key,
        )
    if column_type.is_naive:
        return "TIMESTAMP"
    if column_type.is_utc:
        return "TIMESTAMPTZ"
    # SQL DDL has no per-column zones: TIMESTAMPTZ stores a UTC instant
    raise dl_excs.DataTypeUnsupportedTimestampExc(
        unit=column_type.unit,
        tz_key=column_type.tz_key,
    )


def render_column(
    colspec: core.ColumnSpec,
    *,
    backend: str,
    dialect: sql_types.Dialects,
    type_renderers: cabc.Mapping[sql_types.ColumnTypeKey, sql_types.SqlTypeRenderer],
) -> str:
    if isinstance(colspec.type, (datatypes.Scalars, datatypes.BackendScalars)):
        renderer = type_renderers.get(colspec.type)
    else:
        renderer = type_renderers.get(type(colspec.type))
    if renderer is None:
        raise dl_excs.CantRepresentColumnSpecExc(
            name=colspec.name,
            type=colspec.type,
            backend=backend,
            reason="type renderer not registered",
        )

    try:
        sql_type = renderer(colspec.type)
    except dl_excs.BaseDolotoExc as e:
        raise dl_excs.CantRepresentColumnSpecExc(
            name=colspec.name,
            type=colspec.type,
            backend=backend,
            reason=str(e),
        ) from e

    column_ident = exp.to_identifier(colspec.name, quoted=True).sql(dialect=dialect)
    column_sql = f"{column_ident} {sql_type}"
    if colspec.nullable:
        return column_sql
    return column_sql + " NOT NULL"
