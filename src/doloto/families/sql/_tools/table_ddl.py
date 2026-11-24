from __future__ import annotations

import typing as t

from sqlglot import expressions as exp


if t.TYPE_CHECKING:
    from collections import abc as cabc

    from doloto import core
    from doloto.families.sql import types as sql_types


def render_create_table(
    *,
    db_schema: str,
    db_table: str,
    schema_spec: core.SchemaSpec,
    render_colspec: cabc.Callable[[core.ColumnSpec], str],
    dialect: sql_types.Dialects,
    if_not_exists: bool = False,
) -> str:
    ddl_cmd = "CREATE TABLE"
    if if_not_exists:
        ddl_cmd += " IF NOT EXISTS"
    ddl_table = exp.Table(
        this=exp.Identifier(this=db_table, quoted=True),
        db=exp.Identifier(this=db_schema, quoted=True),
    )
    ddl_table_ident = ddl_table.sql(dialect=dialect)
    ddl_items = [render_colspec(colspec) for colspec in schema_spec.columns]
    if schema_spec.primary_key:
        pk_idents = ", ".join(
            exp.to_identifier(name, quoted=True).sql(dialect=dialect)
            for name in schema_spec.primary_key
        )
        ddl_items.append(f"PRIMARY KEY ({pk_idents})")
    return f"{ddl_cmd} {ddl_table_ident} ({', '.join(ddl_items)})"


def render_drop_table(
    *,
    db_schema: str,
    db_table: str,
    dialect: sql_types.Dialects,
    if_exists: bool = False,
    cascade: bool = False,
) -> str:
    table = exp.table_(db_table, db=db_schema)
    # TODO: drop `this=` once sqlglot < 30 is unsupported (`tables=` since 30)
    drop = exp.Drop(
        this=table,
        tables=[table.copy()],
        kind="TABLE",
        exists=if_exists,
        cascade=cascade,
    )
    ddl: str = drop.sql(dialect=dialect, identify=True)
    return ddl


def render_rename_table(
    *,
    db_schema: str,
    src_table_name: str,
    dst_table_name: str,
    dialect: sql_types.Dialects,
) -> str:
    alter = exp.Alter(
        this=exp.table_(src_table_name, db=db_schema),
        kind="TABLE",
        actions=[exp.AlterRename(this=exp.to_identifier(dst_table_name))],
    )
    ddl: str = alter.sql(dialect=dialect, identify=True)
    return ddl
