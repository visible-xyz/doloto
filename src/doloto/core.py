from __future__ import annotations

import abc
import dataclasses as dcs
import typing as t

from doloto import datatypes
from doloto import exceptions as excs
from doloto._tools import immutables


if t.TYPE_CHECKING:
    from collections import abc as cabc
    import logging


type ColumnDataType = (
    datatypes.Scalars
    | datatypes.BackendScalars
    | datatypes.BackendDataType
    | datatypes.Varchar
    | datatypes.Decimal
    | datatypes.Timestamp
    | datatypes.Uuid
)

type LoggerFactory = cabc.Callable[[str], logging.Logger]


class AbstractFileFormat(abc.ABC):
    __slots__ = ()

    @property
    @abc.abstractmethod
    def filename_extension(self) -> str: ...


@dcs.dataclass(frozen=True, kw_only=True, slots=True)
class ParquetFormat(AbstractFileFormat):
    @property
    def filename_extension(self) -> str:
        return "parquet"


@dcs.dataclass(frozen=True, kw_only=True, slots=True)
class DsvFormat(AbstractFileFormat):
    """Configurable delimiter-separated values."""

    delimiter: str
    header: bool
    null_marker: str | None
    filename_extension: str


@dcs.dataclass(frozen=True, kw_only=True, slots=True)
class FlexibleCsvFormat(DsvFormat):
    """Comma-separated values, configurable apart from the delimiter."""

    delimiter: str = dcs.field(default=",", init=False)
    filename_extension: str = dcs.field(default="csv", init=False)


_MISSING = object()


@dcs.dataclass(frozen=True, kw_only=True, slots=True)
class ColumnOverride:
    name: str
    type: ColumnDataType | None = None
    nullable: bool | None = None

    def __post_init__(self) -> None:
        if self.type is None and self.nullable is None:
            raise ValueError(f"column override {self.name!r} overrides nothing")


@dcs.dataclass(frozen=True, kw_only=True, slots=True)
class ColumnSpec:
    name: str
    type: ColumnDataType
    nullable: bool = False


@dcs.dataclass(frozen=True, kw_only=True, slots=True)
class SchemaSpecDiff:
    missing: tuple[ColumnSpec, ...]
    extra: tuple[ColumnSpec, ...]
    drifted: tuple[tuple[ColumnSpec, ColumnSpec], ...]
    primary_key_drift: tuple[tuple[str, ...], tuple[str, ...]] | None = None

    def __post_init__(self) -> None:
        if not (self.missing or self.extra or self.drifted or self.primary_key_drift):
            raise excs.SchemaSpecDiffEmptyExc()

    @property
    def is_compatible(self) -> bool:
        return not self.is_incompatible

    @property
    def is_incompatible(self) -> bool:
        return bool(self.drifted or self.primary_key_drift)

    def __str__(self) -> str:
        missing_names = ", ".join(col.name for col in self.missing)
        extra_names = ", ".join(col.name for col in self.extra)
        drifted_names = ", ".join(col.name for col, _other_col in self.drifted)
        rendered = (
            f"missing=[{missing_names}] extra=[{extra_names}] drifted=[{drifted_names}]"
        )
        if self.primary_key_drift:
            self_pk, other_pk = self.primary_key_drift
            rendered += (
                f" primary_key=[{', '.join(self_pk)}] -> [{', '.join(other_pk)}]"
            )
        return rendered


class SchemaSpec(immutables.PicklableImmutable):
    __slots__ = ("_by_name", "columns", "name", "primary_key")

    name: str
    primary_key: tuple[str, ...]
    columns: tuple[ColumnSpec, ...]
    _by_name: dict[str, ColumnSpec]

    def __init__(
        self,
        *,
        name: str,
        primary_key: str | cabc.Iterable[str],
        columns: cabc.Iterable[ColumnSpec],
    ) -> None:
        column_specs = tuple(columns)
        if isinstance(primary_key, str):
            primary_key = (primary_key,)
        self._set_attrs(
            name=name,
            columns=column_specs,
            primary_key=tuple(primary_key),
            _by_name={col.name: col for col in column_specs},
        )
        self.__validate_columns()
        for pk in self.primary_key:
            self.__validate_pk(pk)

    def __validate_columns(self) -> None:
        if not self.columns:
            raise excs.SchemaSpecEmptyExc()
        distinct_names = {col.name for col in self.columns}
        if len(distinct_names) != len(self.columns):
            raise excs.SchemaSpecDuplicateColumnsExc(columns=self.columns)

    def __validate_pk(self, column_name: str) -> None:
        if column_name not in self._by_name:
            raise excs.SchemaSpecUnknownPrimaryKeyColumnExc(
                name=self.name,
                column=column_name,
            )
        if self._by_name[column_name].nullable:
            raise excs.SchemaSpecNullablePrimaryKeyExc(
                name=self.name,
                column=column_name,
            )

    def __eq__(self, other: object) -> bool:
        if other.__class__ is not self.__class__:
            return NotImplemented
        return (
            self.columns == other.columns
            and self.name == other.name
            and self.primary_key == other.primary_key
        )

    def __hash__(self) -> int:
        return hash((self.columns, self.name, self.primary_key))

    def _get_state(self) -> dict[str, t.Any]:
        return dict(
            name=self.name,
            primary_key=self.primary_key,
            columns=self.columns,
            _by_name=self._by_name,
        )

    def __str__(self) -> str:
        columns = ", ".join(col.name for col in self.columns)
        pk = ", ".join(self.primary_key)
        return f"{self.name}: {len(self.columns)} columns [{columns}], pk [{pk}]"

    def raise_on_missing_primary_key(self) -> None:
        if not self.primary_key:
            raise excs.SchemaSpecMissingPrimaryKeyExc(name=self.name)

    def get_column_names(self, pk: bool | None = None) -> tuple[str, ...]:
        if pk is None:
            return tuple(col.name for col in self.columns)
        if pk:
            return self.primary_key
        not_pk_names = self._by_name.keys() - self.primary_key
        return tuple(col.name for col in self.columns if col.name in not_pk_names)

    def get_columns(self, pk: bool | None = None) -> tuple[ColumnSpec, ...]:
        if pk is None:
            return self.columns
        return tuple(self._by_name[name] for name in self.get_column_names(pk))

    def get_column_spec(self, name: str, default: t.Any = _MISSING) -> ColumnSpec:
        col_spec: ColumnSpec = self._by_name.get(name, default)
        if col_spec is _MISSING:
            raise excs.SchemaSpecMissingColumnExc(name=name)
        return col_spec

    def narrow_to(
        self,
        columns: cabc.Iterable[str],
        *,
        allow_drop_pk: bool = False,
    ) -> t.Self:
        narrowed = tuple(self.get_column_spec(column) for column in columns)
        lost_pk_cols = set(self.primary_key).difference(col.name for col in narrowed)
        if not lost_pk_cols:
            return self.__class__(
                name=self.name,
                primary_key=self.primary_key,
                columns=narrowed,
            )

        if allow_drop_pk:
            return self.__class__(name=self.name, primary_key=(), columns=narrowed)

        raise ValueError(f"{self.name!r} PK missing {lost_pk_cols} in narrowed columns")

    def renamed(self, name: str) -> t.Self:
        return self.__class__(
            name=name,
            primary_key=self.primary_key,
            columns=self.columns,
        )

    def retyped(
        self,
        column_types: cabc.Mapping[str, ColumnDataType],
        *,
        strict: bool = True,
    ) -> t.Self:
        names = set(column_types)
        if strict:
            unknown = names.difference(self._by_name)
            if unknown:
                raise ValueError(f"{self.name!r} has no columns {sorted(unknown)}")
        if names.isdisjoint(self._by_name):
            return self
        return self.__class__(
            name=self.name,
            primary_key=self.primary_key,
            columns=(
                dcs.replace(col, type=column_types.get(col.name, col.type))
                for col in self.columns
            ),
        )

    def renamed_columns(
        self,
        renames: cabc.Mapping[str, str],
        *,
        strict: bool = True,
    ) -> t.Self:
        """Rename columns by the mapping; the primary key follows them."""
        names = set(renames)
        if strict:
            unknown = names.difference(self._by_name)
            if unknown:
                raise ValueError(f"{self.name!r} has no columns {sorted(unknown)}")
        if names.isdisjoint(self._by_name):
            return self
        return self.__class__(
            name=self.name,
            primary_key=tuple(renames.get(pk, pk) for pk in self.primary_key),
            columns=(
                dcs.replace(col, name=renames.get(col.name, col.name))
                for col in self.columns
            ),
        )

    def compare(self, other: t.Self) -> SchemaSpecDiff | None:
        missing: list[ColumnSpec] = []
        drifted: list[tuple[ColumnSpec, ColumnSpec]] = []
        for col_spec in self.columns:
            other_col_spec = other.get_column_spec(col_spec.name, None)
            if other_col_spec is None:
                missing.append(col_spec)
            elif other_col_spec != col_spec:
                drifted.append((col_spec, other_col_spec))
        extra = tuple(
            col_spec
            for col_spec in other.columns
            if self.get_column_spec(col_spec.name, None) is None
        )
        primary_key_drift = None
        if self.primary_key != other.primary_key:
            primary_key_drift = (self.primary_key, other.primary_key)
        if missing or extra or drifted or primary_key_drift:
            return SchemaSpecDiff(
                missing=tuple(missing),
                extra=extra,
                drifted=tuple(drifted),
                primary_key_drift=primary_key_drift,
            )
        return None

    def is_subset_of(self, other: t.Self) -> bool:
        diff = self.compare(other)
        if diff is None:
            return True
        return diff.is_compatible and not diff.missing

    def is_superset_of(self, other: t.Self) -> bool:
        diff = self.compare(other)
        if diff is None:
            return True
        return diff.is_compatible and not diff.extra
