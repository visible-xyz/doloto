from __future__ import annotations

import typing as t

from doloto import core
from doloto.backends.pg import _tools
from doloto.families.sql import types as sql_types
from doloto.families.sql._tools import aggr
from doloto.families.sql._tools import loading
from doloto.families.sql._tools import table_ddl
from doloto.families.sql._tools import view_ddl


if t.TYPE_CHECKING:
    from collections import abc as cabc

    from sqlglot import expressions as exp


# ---------------------------------------------------------------------------
# Validations
# ---------------------------------------------------------------------------


def validate_table_name(table_name: str) -> None:
    _tools.validate_ident("table name", table_name)


def validate_schema_name(schema_name: str) -> None:
    _tools.validate_ident("schema name", schema_name)


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


def list_tables(
    query_executor: sql_types.QueryExecutor,
    *,
    db_schema: str,
) -> tuple[str, ...]:
    rows = query_executor(f"""
        SELECT c.relname AS table_name
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = {_tools.quote_literal(db_schema)}
          AND c.relkind = 'r'
        ORDER BY c.relname
    """)
    return tuple(row["table_name"] for row in rows)


def table_stats(
    query_executor: sql_types.QueryExecutor,
    *,
    db_schema: str,
    db_table: str,
    count_rows: bool = False,
    count_null_columns: str | cabc.Iterable[str] | None = None,
    count_distinct_columns: str | cabc.Iterable[str] | None = None,
    min_columns: str | cabc.Iterable[str] | None = None,
    max_columns: str | cabc.Iterable[str] | None = None,
    sum_columns: str | cabc.Iterable[str] | None = None,
    avg_columns: str | cabc.Iterable[str] | None = None,
) -> sql_types.TableStats:
    return aggr.table_stats(
        query_executor,
        db_schema=db_schema,
        db_table=db_table,
        dialect=sql_types.Dialects.POSTGRES,
        count_rows=count_rows,
        count_null_columns=count_null_columns,
        count_distinct_columns=count_distinct_columns,
        min_columns=min_columns,
        max_columns=max_columns,
        sum_columns=sum_columns,
        avg_columns=avg_columns,
    )


# ---------------------------------------------------------------------------
# Full Table Management
# ---------------------------------------------------------------------------


def create_table(
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    db_schema: str,
    schema_spec: core.SchemaSpec,
    db_table: str | None = None,
    if_not_exists: bool = False,
) -> None:
    ddl = table_ddl.render_create_table(
        db_schema=db_schema,
        db_table=db_table or schema_spec.name,
        schema_spec=schema_spec,
        render_colspec=_tools.colspec_to_sql,
        dialect=sql_types.Dialects.POSTGRES,
        if_not_exists=if_not_exists,
    )
    stmt_executor(ddl)


def create_table_if_not_exists(
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    db_schema: str,
    schema_spec: core.SchemaSpec,
    db_table: str | None = None,
) -> None:
    create_table(
        stmt_executor,
        db_schema=db_schema,
        db_table=db_table,
        schema_spec=schema_spec,
        if_not_exists=True,
    )


def recreate_table(
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    db_schema: str,
    schema_spec: core.SchemaSpec,
    db_table: str | None = None,
) -> None:
    db_table = db_table or schema_spec.name
    drop_table(
        stmt_executor,
        db_schema=db_schema,
        db_table=db_table,
        if_exists=True,
    )
    create_table(
        stmt_executor,
        db_schema=db_schema,
        db_table=db_table,
        schema_spec=schema_spec,
    )


def drop_table(
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    db_schema: str,
    db_table: str,
    if_exists: bool = False,
    cascade: bool = False,
) -> None:
    ddl = table_ddl.render_drop_table(
        db_schema=db_schema,
        db_table=db_table,
        dialect=sql_types.Dialects.POSTGRES,
        if_exists=if_exists,
        cascade=cascade,
    )
    stmt_executor(ddl)


def drop_table_if_exists(
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    db_schema: str,
    db_table: str,
) -> None:
    drop_table(
        stmt_executor,
        db_schema=db_schema,
        db_table=db_table,
        if_exists=True,
    )


def rename_table(
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    db_schema: str,
    src_table_name: str,
    dst_table_name: str,
) -> None:
    ddl = table_ddl.render_rename_table(
        db_schema=db_schema,
        src_table_name=src_table_name,
        dst_table_name=dst_table_name,
        dialect=sql_types.Dialects.POSTGRES,
    )
    stmt_executor(ddl)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


def create_view(
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    db_schema: str,
    view_name: str,
    select: exp.Expression,
    comment: str | None = None,
) -> None:
    ddl = view_ddl.render_create_view(
        db_schema=db_schema,
        view_name=view_name,
        select=select,
        dialect=sql_types.Dialects.POSTGRES,
    )
    stmt_executor(ddl)
    if comment:
        comment_on_view(
            stmt_executor,
            db_schema=db_schema,
            view_name=view_name,
            comment=comment,
        )


def drop_view(
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    db_schema: str,
    view_name: str,
    if_exists: bool = False,
    cascade: bool = False,
) -> None:
    ddl = view_ddl.render_drop_view(
        db_schema=db_schema,
        view_name=view_name,
        dialect=sql_types.Dialects.POSTGRES,
        if_exists=if_exists,
        cascade=cascade,
    )
    stmt_executor(ddl)


def drop_view_if_exists(
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    db_schema: str,
    view_name: str,
    cascade: bool = False,
) -> None:
    drop_view(
        stmt_executor,
        db_schema=db_schema,
        view_name=view_name,
        if_exists=True,
        cascade=cascade,
    )


def recreate_view(
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    db_schema: str,
    view_name: str,
    select: exp.Expression,
    comment: str | None = None,
) -> None:
    drop_view(
        stmt_executor,
        db_schema=db_schema,
        view_name=view_name,
        if_exists=True,
    )
    create_view(
        stmt_executor,
        db_schema=db_schema,
        view_name=view_name,
        select=select,
        comment=comment,
    )


def comment_on_view(
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    db_schema: str,
    view_name: str,
    comment: str,
) -> None:
    ddl = view_ddl.render_comment_on_view(
        db_schema=db_schema,
        view_name=view_name,
        comment=comment,
        dialect=sql_types.Dialects.POSTGRES,
    )
    stmt_executor(ddl)


# ---------------------------------------------------------------------------
# Doloto Schema / Column Specs
# ---------------------------------------------------------------------------


@t.overload
def load_schema_specs(
    query_executor: sql_types.QueryExecutor,
    *,
    db_schema: str,
    db_tables: cabc.Iterable[sql_types.SchemaLoadRequest],
    overrides: cabc.Mapping[str, cabc.Iterable[core.ColumnOverride]] | None = None,
    aliases: cabc.Mapping[str, cabc.Mapping[str, str]] | None = None,
    allow_missing: t.Literal[False],
    backend_types: sql_types.BackendTypesPolicy = sql_types.BackendTypesPolicy.FALLBACK,
) -> dict[str, core.SchemaSpec]: ...


@t.overload
def load_schema_specs(
    query_executor: sql_types.QueryExecutor,
    *,
    db_schema: str,
    db_tables: cabc.Iterable[sql_types.SchemaLoadRequest],
    overrides: cabc.Mapping[str, cabc.Iterable[core.ColumnOverride]] | None = None,
    aliases: cabc.Mapping[str, cabc.Mapping[str, str]] | None = None,
    allow_missing: t.Literal[True] = True,
    backend_types: sql_types.BackendTypesPolicy = sql_types.BackendTypesPolicy.FALLBACK,
) -> dict[str, core.SchemaSpec | None]: ...


@t.overload
def load_schema_specs(
    query_executor: sql_types.QueryExecutor,
    *,
    db_schema: str,
    db_tables: cabc.Iterable[sql_types.SchemaLoadRequest],
    overrides: cabc.Mapping[str, cabc.Iterable[core.ColumnOverride]] | None = None,
    aliases: cabc.Mapping[str, cabc.Mapping[str, str]] | None = None,
    allow_missing: bool,
    backend_types: sql_types.BackendTypesPolicy = sql_types.BackendTypesPolicy.FALLBACK,
) -> dict[str, core.SchemaSpec] | dict[str, core.SchemaSpec | None]: ...


def load_schema_specs(
    query_executor: sql_types.QueryExecutor,
    *,
    db_schema: str,
    db_tables: cabc.Iterable[sql_types.SchemaLoadRequest],
    overrides: cabc.Mapping[str, cabc.Iterable[core.ColumnOverride]] | None = None,
    aliases: cabc.Mapping[str, cabc.Mapping[str, str]] | None = None,
    allow_missing: bool = True,
    backend_types: sql_types.BackendTypesPolicy = sql_types.BackendTypesPolicy.FALLBACK,
) -> dict[str, core.SchemaSpec] | dict[str, core.SchemaSpec | None]:
    sql_types.BackendTypesPolicy(backend_types)  # fails on a non-member
    table_to_columns = loading.make_table_to_columns(db_tables)
    rows = query_executor(f"""
        SELECT
            cls.relname AS table_name
          , attr.attname AS name
          , attr.atttypid::regtype::text AS data_type
          , information_schema._pg_char_max_length(attr.atttypid, attr.atttypmod) AS char_length
          , information_schema._pg_numeric_precision(attr.atttypid, attr.atttypmod) AS precision
          , information_schema._pg_numeric_scale(attr.atttypid, attr.atttypmod) AS scale
          , NOT attr.attnotnull AS nullable
        FROM pg_attribute attr
        JOIN pg_class cls ON cls.oid = attr.attrelid
        JOIN pg_namespace ns ON ns.oid = cls.relnamespace
        WHERE ns.nspname = {_tools.quote_literal(db_schema)}
          AND cls.relname IN ({_tools.quote_and_join_literals(*table_to_columns)})
          AND attr.attnum > 0 AND NOT attr.attisdropped
        ORDER BY cls.relname, attr.attnum
    """)
    cols_by_table = loading.collect_column_specs(
        rows,
        db_schema=db_schema,
        db_tables=table_to_columns,
        overrides=overrides,
        make_colspec=_tools.make_column_spec_from_catalog_row,
        allow_missing=allow_missing,
    )
    pks_by_table = _tools.load_primary_keys(
        query_executor,
        db_schema=db_schema,
        db_tables=table_to_columns,
    )
    specs = loading.build_schema_specs(
        cols_by_table=cols_by_table,
        pks_by_table=pks_by_table,
        db_schema=db_schema,
        db_tables=table_to_columns,
    )
    for db_table, renames in (aliases or {}).items():
        spec = specs.get(db_table)
        if spec is not None:
            specs[db_table] = spec.renamed_columns(renames)
    return specs


@t.overload
def load_schema_spec(
    query_executor: sql_types.QueryExecutor,
    *,
    db_schema: str,
    db_table: str,
    name: str | None = None,
    columns: cabc.Iterable[str] | None = None,
    overrides: cabc.Iterable[core.ColumnOverride] | None = None,
    allow_missing: t.Literal[False],
    backend_types: sql_types.BackendTypesPolicy = sql_types.BackendTypesPolicy.FALLBACK,
) -> core.SchemaSpec: ...


@t.overload
def load_schema_spec(
    query_executor: sql_types.QueryExecutor,
    *,
    db_schema: str,
    db_table: str,
    name: str | None = None,
    columns: cabc.Iterable[str] | None = None,
    overrides: cabc.Iterable[core.ColumnOverride] | None = None,
    allow_missing: t.Literal[True] = True,
    backend_types: sql_types.BackendTypesPolicy = sql_types.BackendTypesPolicy.FALLBACK,
) -> core.SchemaSpec | None: ...


@t.overload
def load_schema_spec(
    query_executor: sql_types.QueryExecutor,
    *,
    db_schema: str,
    db_table: str,
    name: str | None = None,
    columns: cabc.Iterable[str] | None = None,
    overrides: cabc.Iterable[core.ColumnOverride] | None = None,
    allow_missing: bool,
    backend_types: sql_types.BackendTypesPolicy = sql_types.BackendTypesPolicy.FALLBACK,
) -> core.SchemaSpec | None: ...


def load_schema_spec(
    query_executor: sql_types.QueryExecutor,
    *,
    db_schema: str,
    db_table: str,
    name: str | None = None,
    columns: cabc.Iterable[str] | None = None,
    overrides: cabc.Iterable[core.ColumnOverride] | None = None,
    allow_missing: bool = True,
    backend_types: sql_types.BackendTypesPolicy = sql_types.BackendTypesPolicy.FALLBACK,
) -> core.SchemaSpec | None:
    request: sql_types.SchemaLoadRequest = db_table
    if columns:
        request = (db_table, columns)
    specs = load_schema_specs(
        query_executor,
        db_schema=db_schema,
        db_tables=(request,),
        overrides={db_table: overrides or ()},
        allow_missing=allow_missing,
        backend_types=backend_types,
    )
    schema_spec = specs[db_table]
    if schema_spec and name:
        return schema_spec.renamed(name)
    return schema_spec
