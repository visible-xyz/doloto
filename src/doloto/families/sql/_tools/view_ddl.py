from __future__ import annotations

import typing as t

from sqlglot import expressions as exp


if t.TYPE_CHECKING:
    from doloto.families.sql import types as sql_types


def render_create_view(
    *,
    db_schema: str,
    view_name: str,
    select: exp.Expression,
    dialect: sql_types.Dialects,
) -> str:
    create = exp.Create(
        this=exp.table_(view_name, db=db_schema),
        kind="VIEW",
        expression=select,
    )
    ddl: str = create.sql(dialect=dialect, identify=True)
    return ddl


def render_drop_view(
    *,
    db_schema: str,
    view_name: str,
    dialect: sql_types.Dialects,
    if_exists: bool = False,
    cascade: bool = False,
) -> str:
    view = exp.table_(view_name, db=db_schema)
    # TODO: drop `this=` once sqlglot < 30 is unsupported (`tables=` since 30)
    drop = exp.Drop(
        this=view,
        tables=[view.copy()],
        kind="VIEW",
        exists=if_exists,
        cascade=cascade,
    )
    ddl: str = drop.sql(dialect=dialect, identify=True)
    return ddl


def render_comment_on_view(
    *,
    db_schema: str,
    view_name: str,
    comment: str,
    dialect: sql_types.Dialects,
) -> str:
    comment_on = exp.Comment(
        this=exp.Table(
            this=exp.Identifier(this=view_name, quoted=True),
            db=exp.Identifier(this=db_schema, quoted=True),
        ),
        kind="VIEW",
        expression=exp.Literal.string(comment),
    )
    ddl: str = comment_on.sql(dialect=dialect, identify=True)
    return ddl
