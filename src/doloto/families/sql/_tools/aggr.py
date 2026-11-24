from __future__ import annotations

import typing as t

from sqlglot import expressions as exp

from doloto import exceptions as dl_excs
from doloto.families.sql import types as sql_types


if t.TYPE_CHECKING:
    from collections import abc as cabc


def table_stats(
    query_executor: sql_types.QueryExecutor,
    *,
    db_schema: str,
    db_table: str,
    dialect: sql_types.Dialects,
    count_rows: bool = False,
    count_null_columns: str | cabc.Iterable[str] | None = None,
    count_distinct_columns: str | cabc.Iterable[str] | None = None,
    min_columns: str | cabc.Iterable[str] | None = None,
    max_columns: str | cabc.Iterable[str] | None = None,
    sum_columns: str | cabc.Iterable[str] | None = None,
    avg_columns: str | cabc.Iterable[str] | None = None,
) -> sql_types.TableStats:
    def normalize(columns: str | cabc.Iterable[str] | None) -> tuple[str, ...]:
        if columns is None:
            return ()
        if isinstance(columns, str):
            return (columns,)
        return tuple(columns)

    count_null_columns = normalize(count_null_columns)
    count_distinct_columns = normalize(count_distinct_columns)
    min_columns = normalize(min_columns)
    max_columns = normalize(max_columns)
    sum_columns = normalize(sum_columns)
    avg_columns = normalize(avg_columns)

    projections = []
    if count_rows:
        projections.append(exp.func("COUNT", exp.Star()).as_("rows"))
    for col in count_null_columns:
        count_null = exp.Sub(
            this=exp.func("COUNT", exp.Star()),
            expression=exp.Count(this=exp.column(col)),
        )
        projections.append(count_null.as_(f"count_null__{col}"))
    for col in count_distinct_columns:
        distinct = exp.Distinct(expressions=[exp.column(col)])
        projections.append(exp.Count(this=distinct).as_(f"count_distinct__{col}"))
    for col in min_columns:
        projections.append(exp.Min(this=exp.column(col)).as_(f"min__{col}"))
    for col in max_columns:
        projections.append(exp.Max(this=exp.column(col)).as_(f"max__{col}"))
    for col in sum_columns:
        projections.append(exp.Sum(this=exp.column(col)).as_(f"sum__{col}"))
    for col in avg_columns:
        projections.append(exp.Avg(this=exp.column(col)).as_(f"avg__{col}"))

    dl_excs.EmptyValueExc.validate(projections, label="aggregates")
    select = exp.select(*projections).from_(exp.table_(db_table, db=db_schema))
    row = query_executor(select.sql(dialect=dialect, identify=True))[0]
    stats = sql_types.TableStats()
    if count_rows:
        stats["rows"] = int(row["rows"])
    if count_null_columns:
        stats["count_null_values"] = {
            col: row[f"count_null__{col}"] for col in count_null_columns
        }
    if count_distinct_columns:
        stats["count_distinct_values"] = {
            column: row[f"count_distinct__{column}"]
            for column in count_distinct_columns
        }
    if min_columns:
        stats["min_values"] = {column: row[f"min__{column}"] for column in min_columns}
    if max_columns:
        stats["max_values"] = {column: row[f"max__{column}"] for column in max_columns}
    if sum_columns:
        stats["sum_values"] = {column: row[f"sum__{column}"] for column in sum_columns}
    if avg_columns:
        stats["avg_values"] = {column: row[f"avg__{column}"] for column in avg_columns}
    return stats
