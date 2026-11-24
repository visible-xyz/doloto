from __future__ import annotations

import typing as t

from psycopg2 import extras


if t.TYPE_CHECKING:
    from psycopg2 import extensions as psycopg2_ext

    from doloto.families.sql import types as sql_types


@t.overload
def from_connection(
    conn: psycopg2_ext.connection,
    *,
    no_result: t.Literal[False] = False,
) -> sql_types.QueryExecutor: ...


@t.overload
def from_connection(
    conn: psycopg2_ext.connection,
    *,
    no_result: t.Literal[True],
) -> sql_types.QueryExecutorWithoutResult: ...


def from_connection(
    conn: psycopg2_ext.connection,
    *,
    no_result: bool = False,
) -> sql_types.QueryExecutor | sql_types.QueryExecutorWithoutResult:
    if no_result:

        def no_result_executor(sql: str) -> None:
            with conn.cursor() as cursor:
                cursor.execute(sql)

        return no_result_executor

    def query_executor(sql: str) -> tuple[dict[str, t.Any], ...]:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cursor:
            cursor.execute(sql)
            return tuple(cursor.fetchall())

    return query_executor
