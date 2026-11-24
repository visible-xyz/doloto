from __future__ import annotations

import typing as t

from doloto import exceptions as excs


if t.TYPE_CHECKING:
    from doloto import core


class BaseRedshiftBackendExc(excs.BaseDolotoExc):
    __template__ = "redshift backend error"


class SvvVarcharLengthMissingExc(BaseRedshiftBackendExc):
    __template__ = "varchar column {name} reports no length in svv"
    name: str


class SvvNumericParamsMissingExc(BaseRedshiftBackendExc):
    __template__ = "numeric column {name} reports no precision/scale in svv"
    name: str


class MisalignedVarcharExc(BaseRedshiftBackendExc):
    __template__ = (
        "varchar({byte_length}) column {name} is not {bytes_per_char}x-chars"
        " wide — the table was not created by this tooling"
    )
    byte_length: int
    bytes_per_char: int
    name: str


class UnsupportedVarcharByteLengthExc(BaseRedshiftBackendExc):
    __template__ = "unsupported varchar({byte_length}) byte length"
    byte_length: int


class UnsupportedRedshiftTypeExc(BaseRedshiftBackendExc):
    __template__ = "unsupported Redshift type {data_type} of column {name}"
    data_type: str
    name: str


class BackendTypeNotAllowedExc(BaseRedshiftBackendExc):
    __template__ = (
        "Redshift-local type {data_type} of column {name} is not allowed here"
    )
    data_type: str
    name: str


class UnsupportedFileFormatExc(BaseRedshiftBackendExc):
    __template__ = "unsupported file format {file_format} for Redshift {statement}"
    file_format: core.AbstractFileFormat
    statement: str


class CantReduceTableExc(BaseRedshiftBackendExc):
    __template__ = "can't reduce table {db_table} to spec: {reason}"
    db_schema: str
    db_table: str
    reason: str
