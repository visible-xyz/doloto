from __future__ import annotations

import dataclasses as dcs
import hashlib
import logging
import typing as t

from sqlglot import expressions as exp

from doloto import core
from doloto.backends.redshift import api as rs_api
from doloto.extensions.redshift_refviews import defs as rv_defs
from doloto.families.sql import types as sql_types


if t.TYPE_CHECKING:
    from collections import abc as cabc


@dcs.dataclass(slots=True)
class RefviewData:
    refview: rv_defs.Refview
    view_name: str
    select: exp.Select
    marker: str


_SELECT_HASH_COMMENT_TPL = "refview_select_sha256={digest}"
_VIEW_IDENTITY_TPL = "{select_sql} | {no_schema_binding}"


def make_hash_comment(select: exp.Select, no_schema_binding: bool) -> str:
    identity = _VIEW_IDENTITY_TPL.format(
        select_sql=select.sql(dialect=sql_types.Dialects.REDSHIFT, identify=True),
        no_schema_binding=no_schema_binding,
    )
    digest = hashlib.sha256(identity.encode()).hexdigest()
    return _SELECT_HASH_COMMENT_TPL.format(digest=digest)


def drop_stale_views(
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    dst_schema: str,
    current: cabc.Iterable[str],
    desired: cabc.Iterable[str],
    logger_factory: core.LoggerFactory = logging.getLogger,
) -> int:
    log = logger_factory(__name__)
    stale_names = set(current).difference(desired)
    for view_name in stale_names:
        rs_api.drop_view(stmt_executor, db_schema=dst_schema, view_name=view_name)
        log.warning(f"Dropped stale view {dst_schema}.{view_name}")
    return len(stale_names)
