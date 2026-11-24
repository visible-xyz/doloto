from __future__ import annotations

import re
import types
import typing as t

from sqlglot import expressions as exp

from doloto import core
from doloto import datatypes
from doloto.backends.redshift import datatypes as rs_datatypes
from doloto.backends.redshift import exceptions as excs
from doloto.families.sql import types as sql_types
from doloto.families.sql._tools import column_ddl


if t.TYPE_CHECKING:
    from collections import abc as cabc


UTF8_MAX_BYTES_PER_CHAR: t.Final[int] = 4
MAX_VARCHAR_BYTES: t.Final[int] = 65535
_MAX_IDENT_BYTES: t.Final[int] = 127
_IDENT_RE: t.Final[re.Pattern[str]] = re.compile(r"[a-z_][a-z0-9_]*")

_SVV_DATA_TYPE_TO_SCALAR: t.Final[
    types.MappingProxyType[str, datatypes.Scalars | rs_datatypes.Scalars]
] = types.MappingProxyType(
    {
        "smallint": datatypes.Scalars.INT16,
        "integer": datatypes.Scalars.INT32,
        "bigint": datatypes.Scalars.INT64,
        "real": datatypes.Scalars.FLOAT32,
        "double precision": datatypes.Scalars.FLOAT64,
        "date": datatypes.Scalars.DATE,
        "boolean": datatypes.Scalars.BOOL,
        "super": rs_datatypes.Scalars.SUPER,
    },
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
        rs_datatypes.Scalars.SUPER: lambda _column_type: "SUPER",
        datatypes.Varchar: lambda column_type: (
            f"VARCHAR({column_type.char_length * UTF8_MAX_BYTES_PER_CHAR})"
        ),
        rs_datatypes.Varchar: lambda column_type: f"VARCHAR({column_type.byte_length})",
        datatypes.Decimal: column_ddl.render_numeric,
        datatypes.Timestamp: column_ddl.render_timestamp,
    },
)


def quote_literal(value: str) -> str:
    return exp.Literal.string(value).sql(dialect=sql_types.Dialects.REDSHIFT)


def quote_and_join_literals(*values: str) -> str:
    return ", ".join(quote_literal(value) for value in values)


def copy_format_clauses(file_format: core.AbstractFileFormat) -> cabc.Iterator[str]:
    match file_format:
        case core.ParquetFormat():
            yield "FORMAT AS PARQUET"
            yield "SERIALIZETOJSON"
        case core.DsvFormat():
            yield "FORMAT AS CSV"
            yield f"DELIMITER {quote_literal(file_format.delimiter)}"
            if file_format.header:
                yield "IGNOREHEADER 1"
            if file_format.null_marker == "":
                # NULL AS '' is EMPTYASNULL and keeps the default \N marker,
                # so the marker is replaced with '\0' below
                yield "EMPTYASNULL"
            if file_format.null_marker:
                yield f"NULL AS {quote_literal(file_format.null_marker)}"
            else:
                # COPY can't disable its NULL marker (default \N), only replace it:
                # a field holding just the byte 0x00 stands in for "no NULLs",
                # text data is unlikely to hold one.
                yield r"NULL AS '\0'"
        case _:
            raise excs.UnsupportedFileFormatExc(
                file_format=file_format,
                statement="COPY",
            )


def unload_format_clauses(file_format: core.AbstractFileFormat) -> cabc.Iterator[str]:
    match file_format:
        case core.ParquetFormat():
            yield "FORMAT AS PARQUET"
        case _:
            raise excs.UnsupportedFileFormatExc(
                file_format=file_format,
                statement="UNLOAD",
            )


def colspec_to_sql(colspec: core.ColumnSpec) -> str:
    return column_ddl.render_column(
        colspec,
        backend="Redshift",
        dialect=sql_types.Dialects.REDSHIFT,
        type_renderers=_TYPE_RENDERERS,
    )


def validate_ident(kind: str, name: str) -> None:
    if not _IDENT_RE.fullmatch(name):
        raise ValueError(f"non-compliant {kind}: {name!r}")
    name_bytes = len(name.encode())
    if name_bytes > _MAX_IDENT_BYTES:
        raise ValueError(
            f"{kind} is longer than {_MAX_IDENT_BYTES} bytes ({name_bytes}): {name!r}",
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
            tc.table_name
          , kcu.column_name AS name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
            ON kcu.constraint_schema = tc.constraint_schema
            AND kcu.constraint_name = tc.constraint_name
        WHERE tc.constraint_type = 'PRIMARY KEY'
          AND tc.table_schema = {quote_literal(db_schema)}
          AND tc.table_name IN ({quote_and_join_literals(*primary_keys)})
        ORDER BY tc.table_name, kcu.ordinal_position
    """)
    for row in rows:
        primary_keys[row["table_name"]].append(row["name"])
    return {db_table: tuple(columns) for db_table, columns in primary_keys.items()}


def make_column_spec_from_svv_row(
    *,
    name: str,
    data_type: str,
    byte_length: int | None,
    precision: int | None,
    scale: int | None,
    nullable: bool,
    column_override: core.ColumnOverride | None = None,
    backend_types: sql_types.BackendTypesPolicy,
) -> core.ColumnSpec:
    override_type = None
    if column_override:
        if column_override.nullable is not None:
            nullable = column_override.nullable
        override_type = column_override.type
    if override_type:
        return core.ColumnSpec(name=name, type=override_type, nullable=nullable)

    column_kwargs: dict[str, t.Any] = dict(name=name, nullable=nullable)
    if data_type == "character varying":
        if byte_length is None:
            raise excs.SvvVarcharLengthMissingExc(name=name)
        if backend_types.is_prefer:
            return core.ColumnSpec(
                **column_kwargs,
                type=rs_datatypes.Varchar(byte_length=byte_length),
            )
        if byte_length % UTF8_MAX_BYTES_PER_CHAR:
            if backend_types.is_never:
                raise excs.MisalignedVarcharExc(
                    byte_length=byte_length,
                    bytes_per_char=UTF8_MAX_BYTES_PER_CHAR,
                    name=name,
                )
            return core.ColumnSpec(
                **column_kwargs,
                type=rs_datatypes.Varchar(byte_length=byte_length),
            )
        return core.ColumnSpec(
            **column_kwargs,
            type=datatypes.Varchar(char_length=byte_length // UTF8_MAX_BYTES_PER_CHAR),
        )
    if data_type == "numeric":
        if precision is None or scale is None:
            raise excs.SvvNumericParamsMissingExc(name=name)
        return core.ColumnSpec(
            **column_kwargs,
            type=datatypes.Decimal(precision=precision, scale=scale),
        )
    if data_type == "timestamp with time zone":
        return core.ColumnSpec(
            **column_kwargs,
            type=datatypes.Timestamp(unit="us", tz_key="UTC"),
        )
    if data_type == "timestamp without time zone":
        return core.ColumnSpec(
            **column_kwargs,
            type=datatypes.Timestamp(unit="us", tz_key=None),
        )
    if data_type in _SVV_DATA_TYPE_TO_SCALAR:
        scalar = _SVV_DATA_TYPE_TO_SCALAR[data_type]
        if backend_types.is_never and isinstance(scalar, datatypes.BackendScalars):
            raise excs.BackendTypeNotAllowedExc(data_type=data_type, name=name)
        return core.ColumnSpec(**column_kwargs, type=scalar)
    raise excs.UnsupportedRedshiftTypeExc(data_type=data_type, name=name)
