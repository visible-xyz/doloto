from collections import abc as cabc
import typing as t

import pyarrow as pa
from pyarrow import compute as pc

from doloto import core
from doloto import datatypes
from doloto import exceptions as dl_excs
from doloto.backends.arrow import exceptions as excs


_META_KEY__MAX_CHAR_LENGTH: t.Final[str] = "doloto:max_char_length"


def _validate_char_length(
    field: pa.Field,
    column: pa.ChunkedArray | pa.Array,
) -> None:
    char_length_text = (field.metadata or {}).get(_META_KEY__MAX_CHAR_LENGTH.encode())
    if char_length_text is None:
        return
    char_length = int(char_length_text)
    max_length = pc.max(pc.utf8_length(column)).as_py()  # type: ignore[attr-defined]
    if max_length is None:  # no values at all (empty or all-null column)
        return
    if max_length > char_length:
        raise excs.CharLengthExceededExc(
            name=field.name,
            char_length=char_length,
            max_length=max_length,
        )


def validate_metadata_constraints(data: pa.Table | pa.RecordBatch) -> None:
    for index, field in enumerate(data.schema):
        if pa.types.is_string(field.type):
            _validate_char_length(field, data.column(index))


def make_field(colspec: core.ColumnSpec) -> pa.Field:
    metadata = None
    if isinstance(colspec.type, datatypes.Varchar):
        # arrow has no bounded strings — the limit survives only as metadata
        arrow_type = pa.string()
        metadata = {_META_KEY__MAX_CHAR_LENGTH: str(colspec.type.char_length)}
    elif isinstance(colspec.type, datatypes.Decimal):
        arrow_type = pa.decimal128(colspec.type.precision, colspec.type.scale)
    elif colspec.type is datatypes.Scalars.INT16:
        arrow_type = pa.int16()
    elif colspec.type is datatypes.Scalars.INT32:
        arrow_type = pa.int32()
    elif colspec.type is datatypes.Scalars.INT64:
        arrow_type = pa.int64()
    elif colspec.type is datatypes.Scalars.FLOAT32:
        arrow_type = pa.float32()
    elif colspec.type is datatypes.Scalars.FLOAT64:
        arrow_type = pa.float64()
    elif colspec.type is datatypes.Scalars.DATE:
        arrow_type = pa.date32()
    elif colspec.type is datatypes.Scalars.BOOL:
        arrow_type = pa.bool_()
    elif colspec.type is datatypes.Scalars.TEXT:
        arrow_type = pa.string()
    elif colspec.type is datatypes.Scalars.JSON:
        arrow_type = pa.json_()
    elif isinstance(colspec.type, datatypes.Timestamp):
        arrow_type = pa.timestamp(colspec.type.unit, tz=colspec.type.tz_key)
    else:
        raise dl_excs.CantRepresentColumnSpecExc(
            name=colspec.name,
            type=colspec.type,
            backend="Arrow",
        )
    return pa.field(
        colspec.name,
        arrow_type,
        nullable=colspec.nullable,
        metadata=metadata,
    )


def make_schema(schema_spec: core.SchemaSpec) -> pa.Schema:
    return pa.schema(make_field(spec) for spec in schema_spec.columns)


def cast_batches(
    batches: cabc.Iterable[pa.RecordBatch],
    *,
    schema: pa.Schema,
    safe: bool = True,
) -> cabc.Iterator[pa.RecordBatch]:
    """Cast batches to `schema`; a safe cast refuses lossy conversions."""
    for batch in batches:
        yield batch.cast(schema, safe=safe)
