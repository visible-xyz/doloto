import dataclasses as dcs
import enum
import typing as t

from doloto import datatypes
from doloto.backends.redshift import exceptions as excs


class Scalars(datatypes.BackendScalars):
    SUPER = enum.auto()


@dcs.dataclass(frozen=True, kw_only=True, slots=True)
class Varchar(datatypes.BackendDataType):
    MAX_BYTE_LENGTH: t.ClassVar[int] = 65535

    byte_length: int

    def __post_init__(self) -> None:
        if not 1 <= self.byte_length <= self.MAX_BYTE_LENGTH:
            raise excs.UnsupportedVarcharByteLengthExc(byte_length=self.byte_length)
