from __future__ import annotations

from collections import abc as cabc
import enum
import typing as t

from miska import enums


if t.TYPE_CHECKING:
    from doloto import core
    from doloto import datatypes


# when a spec gets backend-local types: never (shared only), as a fallback
# where no shared type is exact, or preferred wherever the backend has one
class BackendTypesPolicy(enum.Enum):
    NEVER = enum.auto()
    FALLBACK = enum.auto()
    PREFER = enum.auto()

    @property
    def is_never(self) -> bool:
        return self is BackendTypesPolicy.NEVER

    @property
    def is_fallback(self) -> bool:
        return self is BackendTypesPolicy.FALLBACK

    @property
    def is_prefer(self) -> bool:
        return self is BackendTypesPolicy.PREFER


class Dialects(enums.LowerCaseStrEnum):
    POSTGRES = enum.auto()
    REDSHIFT = enum.auto()


type QueryExecutor = cabc.Callable[[str], tuple[dict[str, t.Any], ...]]
type QueryExecutorWithoutResult = cabc.Callable[[str], None]

# a table to load: its name alone (every column) or with the columns to keep
type SchemaLoadRequest = str | tuple[str, cabc.Iterable[str]]

# dispatch key for a column type: a Scalars member (by identity) or a
# parametric-type class (Varchar/Decimal/...), rendered by a SqlTypeRenderer
type ColumnTypeKey = (
    datatypes.Scalars | datatypes.BackendScalars | type[core.ColumnDataType]
)
type SqlTypeRenderer = cabc.Callable[[t.Any], str]


class TableStats(t.TypedDict, total=False):
    rows: int
    count_null_values: dict[str, int]
    count_distinct_values: dict[str, int]
    min_values: dict[str, t.Any]
    max_values: dict[str, t.Any]
    sum_values: dict[str, t.Any]
    avg_values: dict[str, t.Any]
