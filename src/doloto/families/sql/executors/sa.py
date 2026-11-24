from __future__ import annotations

import typing as t


if t.TYPE_CHECKING:
    from sqlalchemy import engine as sa_engine

    from doloto.families.sql import types as sql_types


@t.overload
def from_connection(
    conn: sa_engine.Connection,
    *,
    no_result: t.Literal[False] = False,
) -> sql_types.QueryExecutor: ...


@t.overload
def from_connection(
    conn: sa_engine.Connection,
    *,
    no_result: t.Literal[True],
) -> sql_types.QueryExecutorWithoutResult: ...


def from_connection(
    conn: sa_engine.Connection,
    *,
    no_result: bool = False,
) -> sql_types.QueryExecutor | sql_types.QueryExecutorWithoutResult:
    if no_result:

        def no_result_executor(sql: str) -> None:
            conn.exec_driver_sql(sql)

        return no_result_executor

    def query_executor(sql: str) -> tuple[dict[str, t.Any], ...]:
        return tuple(dict(row) for row in conn.exec_driver_sql(sql).mappings())

    return query_executor
