from __future__ import annotations

import types
import typing as t

from sqlglot import expressions as exp

from doloto import core
from doloto import datatypes
from doloto.backends.pg import exceptions as excs
from doloto.families.sql import types as sql_types
from doloto.families.sql._tools import column_ddl


if t.TYPE_CHECKING:
    from collections import abc as cabc


_MAX_IDENT_BYTES: t.Final[int] = 63  # NAMEDATALEN - 1

_CHAR_TYPES: t.Final[frozenset[str]] = frozenset(
    ("character varying", "character", "text"),
)
_TYPE_NAME_TO_SCALAR: t.Final[types.MappingProxyType[str, datatypes.Scalars]] = (
    types.MappingProxyType(
        {
            "smallint": datatypes.Scalars.INT16,
            "integer": datatypes.Scalars.INT32,
            "bigint": datatypes.Scalars.INT64,
            "real": datatypes.Scalars.FLOAT32,
            "double precision": datatypes.Scalars.FLOAT64,
            "date": datatypes.Scalars.DATE,
            "boolean": datatypes.Scalars.BOOL,
            "text": datatypes.Scalars.TEXT,
            "json": datatypes.Scalars.JSON,
            "jsonb": datatypes.Scalars.JSON,
        },
    )
)


_TYPE_RENDERERS: t.Final[
    types.MappingProxyType[sql_types.ColumnTypeKey, sql_types.SqlTypeRenderer]
] = types.MappingProxyType(
    {
        datatypes.Scalars.INT16: column_ddl.render_smallint,
        datatypes.Scalars.INT32: column_ddl.render_integer,
        datatypes.Scalars.INT64: column_ddl.render_bigint,
        datatypes.Scalars.FLOAT32: column_ddl.render_real,
        datatypes.Scalars.FLOAT64: column_ddl.render_double_precision,
        datatypes.Scalars.DATE: column_ddl.render_date,
        datatypes.Scalars.BOOL: column_ddl.render_boolean,
        datatypes.Scalars.TEXT: lambda _column_type: "TEXT",
        datatypes.Varchar: lambda column_type: f"VARCHAR({column_type.char_length})",
        datatypes.Decimal: column_ddl.render_numeric,
        datatypes.Timestamp: column_ddl.render_timestamp,
    },
)


def quote_literal(value: str) -> str:
    return exp.Literal.string(value).sql(dialect=sql_types.Dialects.POSTGRES)


def quote_and_join_literals(*values: str) -> str:
    return ", ".join(quote_literal(value) for value in values)


def validate_ident(kind: str, name: str) -> None:
    if not name.isascii():
        raise ValueError(f"non-ascii {kind}: {name!r}")
    name_bytes = len(name.encode())
    if name_bytes > _MAX_IDENT_BYTES:
        raise ValueError(
            f"{kind} is longer than {_MAX_IDENT_BYTES} bytes ({name_bytes}): {name!r}",
        )


def colspec_to_sql(colspec: core.ColumnSpec) -> str:
    return column_ddl.render_column(
        colspec,
        backend="PG",
        dialect=sql_types.Dialects.POSTGRES,
        type_renderers=_TYPE_RENDERERS,
    )


def load_primary_keys(
    query_executor: sql_types.QueryExecutor,
    *,
    db_schema: str,
    db_tables: cabc.Iterable[str],
) -> dict[str, tuple[str, ...]]:
    primary_keys: dict[str, list[str]] = {db_table: [] for db_table in db_tables}
    rows = query_executor(f"""
        SELECT
            cls.relname AS table_name
          , attr.attname AS name
        FROM pg_index ix
        JOIN pg_class cls ON cls.oid = ix.indrelid
        JOIN pg_namespace ns ON ns.oid = cls.relnamespace
        JOIN pg_attribute attr ON attr.attrelid = ix.indrelid AND attr.attnum = ANY(ix.indkey)
        WHERE ns.nspname = {quote_literal(db_schema)}
          AND cls.relname IN ({quote_and_join_literals(*primary_keys)})
          AND ix.indisprimary
        ORDER BY cls.relname, array_position(ix.indkey, attr.attnum)
    """)
    for row in rows:
        primary_keys[row["table_name"]].append(row["name"])
    return {db_table: tuple(columns) for db_table, columns in primary_keys.items()}


def make_column_spec_from_catalog_row(
    *,
    name: str,
    data_type: str,
    char_length: int | None,
    precision: int | None,
    scale: int | None,
    nullable: bool,
    column_override: core.ColumnOverride | None = None,
) -> core.ColumnSpec:
    override_type = None
    if column_override:
        if column_override.nullable is not None:
            nullable = column_override.nullable
        override_type = column_override.type
    if override_type:
        return core.ColumnSpec(name=name, type=override_type, nullable=nullable)

    column_type: core.ColumnDataType
    if data_type in _CHAR_TYPES:
        if char_length is None:  # bare varchar & text have no declared length
            column_type = datatypes.Scalars.TEXT
        else:
            column_type = datatypes.Varchar(char_length=char_length)
    elif data_type == "numeric":
        if precision is None or scale is None:
            raise excs.BareNumericExc(name=name)
        column_type = datatypes.Decimal(precision=precision, scale=scale)
    elif data_type == "timestamp with time zone":
        column_type = datatypes.Timestamp(unit="us", tz_key="UTC")  # microseconds
    elif data_type == "timestamp without time zone":
        column_type = datatypes.Timestamp(unit="us", tz_key=None)  # microseconds
    elif data_type in _TYPE_NAME_TO_SCALAR:
        column_type = _TYPE_NAME_TO_SCALAR[data_type]
    else:
        raise excs.UnsupportedPgTypeExc(data_type=data_type, name=name)
    return core.ColumnSpec(name=name, type=column_type, nullable=nullable)
