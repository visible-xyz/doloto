from __future__ import annotations

import typing as t

from psycopg import rows


if t.TYPE_CHECKING:
    import psycopg

    from doloto.families.sql import types as sql_types


@t.overload
def from_connection(
    conn: psycopg.Connection,
    *,
    no_result: t.Literal[False] = False,
) -> sql_types.QueryExecutor: ...


@t.overload
def from_connection(
    conn: psycopg.Connection,
    *,
    no_result: t.Literal[True],
) -> sql_types.QueryExecutorWithoutResult: ...


def from_connection(
    conn: psycopg.Connection,
    *,
    no_result: bool = False,
) -> sql_types.QueryExecutor | sql_types.QueryExecutorWithoutResult:
    if no_result:

        def no_result_executor(sql: str) -> None:
            conn.execute(sql)

        return no_result_executor

    def query_executor(sql: str) -> tuple[dict[str, t.Any], ...]:
        with conn.cursor(row_factory=rows.dict_row) as cursor:
            return tuple(cursor.execute(sql).fetchall())

    return query_executor
