from __future__ import annotations

import collections
import typing as t

from izulu import _reraise

from doloto import core
from doloto import exceptions as dl_excs
from doloto.families.sql import exceptions as sql_excs
from doloto.families.sql import types as sql_types


if t.TYPE_CHECKING:
    from collections import abc as cabc


def make_table_to_columns(
    schema_load_requests: cabc.Iterable[sql_types.SchemaLoadRequest],
) -> dict[str, tuple[str, ...] | None]:
    table_to_columns: dict[str, tuple[str, ...] | None] = {}
    for request in schema_load_requests:
        if isinstance(request, str):
            table, columns = request, None
        else:
            table, _columns_raw = request
            if isinstance(_columns_raw, str):
                raise TypeError(f"columns of {table!r} must be a collection of strings")
            columns = tuple(_columns_raw)
        if table in table_to_columns:
            raise ValueError(f"table {table!r} requested twice")
        table_to_columns[table] = columns
    if not table_to_columns:
        raise sql_excs.NoTablesRequestedExc()
    return table_to_columns


def _make_ident_to_override(
    overrides: cabc.Mapping[str, cabc.Iterable[core.ColumnOverride]],
) -> dict[tuple[str, str], core.ColumnOverride]:
    ident_to_override = {}
    for db_table, table_overrides in overrides.items():
        for override in table_overrides:
            ident = (db_table, override.name)
            if ident in ident_to_override:
                raise ValueError(
                    f"column {override.name!r} of {db_table!r} overridden twice",
                )
            ident_to_override[ident] = override
    return ident_to_override


def collect_column_specs(
    rows: cabc.Iterable[dict[str, t.Any]],
    *,
    db_schema: str,
    db_tables: cabc.Mapping[str, tuple[str, ...] | None],
    make_colspec: cabc.Callable[..., core.ColumnSpec],
    overrides: cabc.Mapping[str, cabc.Iterable[core.ColumnOverride]] | None = None,
    allow_missing: bool = True,
) -> dict[str, list[core.ColumnSpec]]:
    """Map catalog rows to column specs, grouped by table.

    A table's columns, when requested, restrict it to the listed ones: other
    catalog rows are skipped before typing (their types need not be
    supported), and unless `allow_missing` every listed column has to be
    present.
    """
    ident_to_override = _make_ident_to_override(overrides or {})
    table_to_wanted_cols = {
        db_table: frozenset(columns)
        for db_table, columns in db_tables.items()
        if columns
    }
    problems: dict[str, list[str]] = collections.defaultdict(list)
    cols_by_table: dict[str, list[core.ColumnSpec]] = collections.defaultdict(list)
    for row in rows:
        col_kwargs = dict(row)
        db_table = col_kwargs.pop("table_name")
        col_name = col_kwargs["name"]
        wanted_cols = table_to_wanted_cols.get(db_table)
        if wanted_cols and col_name not in wanted_cols:
            continue
        col_override = ident_to_override.get((db_table, col_name))
        try:
            colspec = make_colspec(**col_kwargs, column_override=col_override)
            cols_by_table[db_table].append(colspec)
        except dl_excs.BaseDolotoExc as err:  # other errors are bugs
            problems[db_table].append(f"column {col_name}: {err}")
    if not allow_missing:
        for db_table in db_tables:
            if cols_by_table[db_table]:
                continue
            if db_table in problems:
                continue
            problems[db_table].append("not found")
        for db_table, wanted_cols in table_to_wanted_cols.items():
            found = {colspec.name for colspec in cols_by_table[db_table]}
            for column in sorted(wanted_cols - found):
                problems[db_table].append(f"column {column}: not found")
    if problems:
        raise sql_excs.TablesNotLoadableExc(
            db_schema=db_schema,
            problems={
                db_table: tuple(table_problems)
                for db_table, table_problems in problems.items()
            },
        )
    return cols_by_table


@t.overload
def build_schema_specs(
    *,
    cols_by_table: dict[str, list[core.ColumnSpec]],
    pks_by_table: dict[str, tuple[str, ...]],
    db_schema: str,
    db_tables: None = None,
) -> dict[str, core.SchemaSpec]: ...


@t.overload
def build_schema_specs(
    *,
    cols_by_table: dict[str, list[core.ColumnSpec]],
    pks_by_table: dict[str, tuple[str, ...]],
    db_schema: str,
    db_tables: cabc.Iterable[str],
) -> dict[str, core.SchemaSpec | None]: ...


def build_schema_specs(
    *,
    cols_by_table: dict[str, list[core.ColumnSpec]],
    pks_by_table: dict[str, tuple[str, ...]],
    db_schema: str,
    db_tables: cabc.Iterable[str] | None = None,
) -> dict[str, core.SchemaSpec] | dict[str, core.SchemaSpec | None]:
    specs = {}
    for db_table, columns in cols_by_table.items():
        with _reraise.add_note(f"{db_schema=} {db_table=}"):
            specs[db_table] = core.SchemaSpec(
                name=db_table,
                primary_key=pks_by_table[db_table],
                columns=columns,
            )
    if db_tables is None:
        return specs
    return {db_table: specs.get(db_table) for db_table in db_tables}
