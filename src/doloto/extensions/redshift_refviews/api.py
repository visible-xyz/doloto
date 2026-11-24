from __future__ import annotations

import dataclasses as dcs
import itertools
import logging
import operator
import re
import typing as t

from doloto import core
from doloto.backends.redshift import api as rs_api
from doloto.extensions.redshift_refviews import _tools
from doloto.extensions.redshift_refviews import defs as rv_defs
from doloto.families.sql import types as sql_types


if t.TYPE_CHECKING:
    from collections import abc as cabc


@dcs.dataclass(slots=True)
class RefviewReconcileStats:
    created: int = 0
    recreated: int = 0
    unchanged: int = 0
    dropped: int = 0

    def record(self, *, existed: bool, out_of_sync: bool) -> None:
        if out_of_sync and existed:
            self.recreated += 1
        elif out_of_sync:
            self.created += 1
        else:
            self.unchanged += 1


class RefviewManager:
    def __init__(self, *, namespace: str, tailmark: str = "refview") -> None:
        if not (namespace and tailmark):
            raise ValueError("namespace and tailmark must be non-empty")
        self._name_prefix = namespace + "__"
        self._name_suffix = "__" + tailmark
        self._name_re = re.compile(
            re.escape(namespace) + "__.+__" + re.escape(tailmark),
        )

    def _make_view_name(self, refview: rv_defs.Refview) -> str:
        view_name = f"{self._name_prefix}{refview.src_relation}{self._name_suffix}"
        rs_api.validate_table_name(view_name)
        return view_name

    def _load_managed_comments(
        self,
        query_executor: sql_types.QueryExecutor,
        *,
        dst_schema: str,
    ) -> dict[str, str | None]:
        all_comments = rs_api.load_view_comments(query_executor, db_schema=dst_schema)
        return {
            view_name: comment
            for view_name, comment in all_comments.items()
            if self._name_re.fullmatch(view_name)
        }

    def _reconcile_schema(
        self,
        query_executor: sql_types.QueryExecutor,
        stmt_executor: sql_types.QueryExecutorWithoutResult,
        *,
        dst_schema: str,
        rvdata: cabc.Iterable[_tools.RefviewData],
        stats: RefviewReconcileStats,
        logger_factory: core.LoggerFactory = logging.getLogger,
    ) -> None:
        log = logger_factory(__name__)
        comments = self._load_managed_comments(query_executor, dst_schema=dst_schema)
        desired_names = set()
        for data in rvdata:
            desired_names.add(data.view_name)
            out_of_sync = comments.get(data.view_name) != data.marker
            if out_of_sync:
                rs_api.recreate_view(
                    stmt_executor,
                    db_schema=dst_schema,
                    view_name=data.view_name,
                    select=data.select,
                    no_schema_binding=data.refview.no_schema_binding,
                    comment=data.marker,
                )
                log.info(f"Recreated view {dst_schema}.{data.view_name}")
            stats.record(existed=data.view_name in comments, out_of_sync=out_of_sync)

        stats.dropped += _tools.drop_stale_views(
            stmt_executor,
            dst_schema=dst_schema,
            current=comments.keys(),
            desired=desired_names,
            logger_factory=logger_factory,
        )

    def _rvdata_by_dest_schema(
        self,
        refviews: cabc.Iterable[rv_defs.Refview],
    ) -> cabc.Iterator[tuple[str, tuple[_tools.RefviewData, ...]]]:
        by_dst_schema = operator.attrgetter("dst_schema")
        for dst_schema, schema_refviews in itertools.groupby(
            sorted(refviews, key=by_dst_schema),
            key=by_dst_schema,
        ):
            rvdata: list[_tools.RefviewData] = []
            for refview in schema_refviews:
                select = refview.make_select()
                rvdata.append(
                    _tools.RefviewData(
                        refview=refview,
                        view_name=self._make_view_name(refview),
                        select=select,
                        marker=_tools.make_hash_comment(
                            select,
                            refview.no_schema_binding,
                        ),
                    ),
                )
            yield dst_schema, tuple(rvdata)

    def reconcile(
        self,
        refviews: cabc.Iterable[rv_defs.Refview],
        *,
        query_executor: sql_types.QueryExecutor,
        stmt_executor: sql_types.QueryExecutorWithoutResult,
        logger_factory: core.LoggerFactory = logging.getLogger,
    ) -> RefviewReconcileStats:
        stats = RefviewReconcileStats()
        for dst_schema, rvdata in self._rvdata_by_dest_schema(refviews):
            self._reconcile_schema(
                query_executor,
                stmt_executor,
                dst_schema=dst_schema,
                rvdata=rvdata,
                stats=stats,
                logger_factory=logger_factory,
            )
        return stats
