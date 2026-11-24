from __future__ import annotations

import typing as t

from sqlglot import expressions as exp

from doloto import exceptions as excs
from doloto.families.sql import glot


if t.TYPE_CHECKING:
    from collections import abc as cabc

    from doloto.families.sql import types as sql_types


def _make_insert_select(
    *,
    db_schema: str,
    src_table_name: str,
    dst_table_name: str,
    column_names: tuple[str, ...],
) -> exp.Expression:
    excs.EmptyValueExc.validate(column_names, label="columns")
    return exp.insert(
        exp.select(*glot.project(column_names)).from_(
            exp.table_(src_table_name, db=db_schema),
        ),
        into=exp.table_(dst_table_name, db=db_schema),
        columns=column_names,
    )


def replace_all_rows(
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    db_schema: str,
    src_table_name: str,
    dst_table_name: str,
    column_names: cabc.Iterable[str],
    dialect: sql_types.Dialects,
) -> None:
    # DELETE FROM "s"."dst"
    delete = exp.Delete(this=exp.table_(dst_table_name, db=db_schema))

    # INSERT INTO "s"."dst" ("pk", "col") SELECT "pk", "col" FROM "s"."src"
    insert = _make_insert_select(
        db_schema=db_schema,
        src_table_name=src_table_name,
        dst_table_name=dst_table_name,
        column_names=tuple(column_names),
    )

    stmt_executor(delete.sql(dialect=dialect, identify=True))
    stmt_executor(insert.sql(dialect=dialect, identify=True))
