from __future__ import annotations

import typing as t


if t.TYPE_CHECKING:
    from adbc_driver_manager import dbapi as adbc_dbapi

    from doloto.families.sql import types as sql_types


@t.overload
def from_connection(
    conn: adbc_dbapi.Connection,
    *,
    no_result: t.Literal[False] = False,
) -> sql_types.QueryExecutor: ...


@t.overload
def from_connection(
    conn: adbc_dbapi.Connection,
    *,
    no_result: t.Literal[True],
) -> sql_types.QueryExecutorWithoutResult: ...


def from_connection(
    conn: adbc_dbapi.Connection,
    *,
    no_result: bool = False,
) -> sql_types.QueryExecutor | sql_types.QueryExecutorWithoutResult:
    if no_result:

        def no_result_executor(sql: str) -> None:
            with conn.cursor() as cursor:
                cursor.execute(sql)

        return no_result_executor

    def query_executor(sql: str) -> tuple[dict[str, t.Any], ...]:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            return tuple(cursor.fetch_arrow_table().to_pylist())

    return query_executor


@t.overload
def from_cursor(
    cursor: adbc_dbapi.Cursor,
    *,
    no_result: t.Literal[False] = False,
) -> sql_types.QueryExecutor: ...


@t.overload
def from_cursor(
    cursor: adbc_dbapi.Cursor,
    *,
    no_result: t.Literal[True],
) -> sql_types.QueryExecutorWithoutResult: ...


def from_cursor(
    cursor: adbc_dbapi.Cursor,
    *,
    no_result: bool = False,
) -> sql_types.QueryExecutor | sql_types.QueryExecutorWithoutResult:
    if no_result:

        def no_result_executor(sql: str) -> None:
            cursor.execute(sql)

        return no_result_executor

    def query_executor(sql: str) -> tuple[dict[str, t.Any], ...]:
        cursor.execute(sql)
        return tuple(cursor.fetch_arrow_table().to_pylist())

    return query_executor
