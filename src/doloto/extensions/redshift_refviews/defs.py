from __future__ import annotations

import typing as t

from sqlglot import expressions as exp


class Refview(t.NamedTuple):
    src_schema: str
    src_relation: str
    src_column_names: tuple[str, ...]
    dst_schema: str
    no_schema_binding: bool = True

    def make_select(self) -> exp.Select:
        columns = (exp.column(col) for col in self.src_column_names)
        relation = exp.table_(self.src_relation, db=self.src_schema)
        return exp.select(*columns).from_(relation)
