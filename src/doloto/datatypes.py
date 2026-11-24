from __future__ import annotations

import dataclasses as dcs
import enum
import typing as t
import zoneinfo

from miska import enums

from doloto import exceptions as excs


if t.TYPE_CHECKING:
    from doloto import core


class Scalars(enums.LowerCaseStrEnum):
    INT16 = enum.auto()
    INT32 = enum.auto()
    INT64 = enum.auto()
    FLOAT32 = enum.auto()
    FLOAT64 = enum.auto()
    DATE = enum.auto()
    BOOL = enum.auto()
    TEXT = enum.auto()
    JSON = enum.auto()

    @classmethod
    def get_integers(cls) -> tuple[Scalars, ...]:
        return cls.INT16, cls.INT32, cls.INT64


class BackendScalars(enums.LowerCaseStrEnum):
    pass


class BackendDataType:
    pass


@dcs.dataclass(frozen=True, kw_only=True, slots=True)
class Varchar:
    MAX_CHAR_LENGTH: t.ClassVar[int] = 16383  # Redshift cap: 65535 bytes / 4 per char

    char_length: int

    def __post_init__(self) -> None:
        if not 1 <= self.char_length <= self.MAX_CHAR_LENGTH:
            raise excs.DataTypeUnsupportedVarcharExc(char_length=self.char_length)


@dcs.dataclass(frozen=True, kw_only=True, slots=True)
class Decimal:
    MAX_PRECISION: t.ClassVar[int] = 38
    MAX_SCALE: t.ClassVar[int] = 37

    precision: int
    scale: int

    def __post_init__(self) -> None:
        if not 1 <= self.precision <= self.MAX_PRECISION:
            raise excs.DataTypeUnsupportedDecimalExc(
                precision=self.precision,
                scale=self.scale,
            )
        if not 0 <= self.scale <= min(self.precision, self.MAX_SCALE):
            raise excs.DataTypeUnsupportedDecimalExc(
                precision=self.precision,
                scale=self.scale,
            )


@dcs.dataclass(frozen=True, kw_only=True, slots=True)
class Timestamp:
    UNITS: t.ClassVar[frozenset[str]] = frozenset(("us",))

    unit: str
    tz_key: str | None

    def __post_init__(self) -> None:
        if self.unit not in self.UNITS:
            raise excs.DataTypeUnsupportedTimestampExc(
                unit=self.unit,
                tz_key=self.tz_key,
            )
        if self.tz_key is not None:
            try:
                zoneinfo.ZoneInfo(self.tz_key)
            except (zoneinfo.ZoneInfoNotFoundError, ValueError) as e:
                raise excs.DataTypeUnsupportedTimestampExc(
                    unit=self.unit,
                    tz_key=self.tz_key,
                ) from e

    @property
    def zone(self) -> zoneinfo.ZoneInfo | None:
        if self.tz_key is None:
            return None
        return zoneinfo.ZoneInfo(self.tz_key)

    @property
    def is_aware(self) -> bool:
        return self.tz_key is not None

    @property
    def is_naive(self) -> bool:
        return self.tz_key is None

    @property
    def is_utc(self) -> bool:
        return self.tz_key == "UTC"


@dcs.dataclass(frozen=True, kw_only=True, slots=True)
class Uuid:
    VERSIONS: t.ClassVar[frozenset[int]] = frozenset(range(1, 9))

    version: int

    def __post_init__(self) -> None:
        if self.version not in self.VERSIONS:
            raise excs.DataTypeUnsupportedUuidExc(version=self.version)


# canonical representations:
#   int32 / int64 / date / bool / text / json
#   uuid1 .. uuid8
#   timestamp / timestamptz
#   varchar(256)
#   decimal(10, 2)
_TYPES_BY_JSON: t.Final[dict[str, core.ColumnDataType]] = {
    **{member.value.lower(): member for member in Scalars},
    **{f"uuid{version}": Uuid(version=version) for version in sorted(Uuid.VERSIONS)},
    "timestamp": Timestamp(unit="us", tz_key=None),
    "timestamptz": Timestamp(unit="us", tz_key="UTC"),
}
_JSONS_BY_TYPE: t.Final[dict[core.ColumnDataType, str]] = {
    column_type: raw for raw, column_type in _TYPES_BY_JSON.items()
}


def as_string(column_type: core.ColumnDataType) -> str:
    if isinstance(column_type, Varchar):
        return f"varchar({column_type.char_length})"
    if isinstance(column_type, Decimal):
        return f"decimal({column_type.precision}, {column_type.scale})"
    return _JSONS_BY_TYPE[column_type]


@t.overload
def from_string(
    raw: str,
    *,
    passthrough_none: t.Literal[False] = False,
) -> core.ColumnDataType: ...


@t.overload
def from_string(
    raw: str | None,
    *,
    passthrough_none: t.Literal[True],
) -> core.ColumnDataType | None: ...


def from_string(
    raw: str | None,
    *,
    passthrough_none: bool = False,
) -> core.ColumnDataType | None:
    if raw is None:
        if passthrough_none:
            return None
        raise ValueError(f"unknown column type: {raw!r}")

    column_type = _TYPES_BY_JSON.get(raw)
    if column_type:
        return column_type

    name, bracket, params = raw.partition("(")
    if not (bracket and params.endswith(")")):
        raise ValueError(f"unknown column type: {raw!r}")

    args = [arg.strip() for arg in params.removesuffix(")").split(",")]
    if name == "varchar":
        (char_length,) = args
        return Varchar(char_length=int(char_length))
    if name == "decimal":
        precision, scale = args
        return Decimal(precision=int(precision), scale=int(scale))

    raise ValueError(f"unknown column type: {raw!r}")
