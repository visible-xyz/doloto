from __future__ import annotations

from collections import abc as cabc
import dataclasses as dcs
import itertools
import logging
import typing as t

import pyarrow as pa
from pyarrow import fs as pafs
from pyarrow import parquet as pq

from doloto import constants as c
from doloto import core
from doloto.families.s3 import types as s3_types


def cleanup_subtree(
    s3ref: s3_types.S3Ref,
    *,
    s3_region: str,
    suppress_error: bool = False,
) -> bool:
    try:
        pafs.S3FileSystem(region=s3_region).delete_dir_contents(s3ref.path)
        return True
    except Exception:
        if suppress_error:
            return False
        raise


@dcs.dataclass(frozen=True, kw_only=True, slots=True)
class S3Part:
    ref: s3_types.S3Ref
    bytes: int
    rows: int


class ManifestorProto(t.Protocol):
    @property
    def filename(self) -> str: ...

    def make_body(self, s3_parts: cabc.Iterable[S3Part], /) -> bytes: ...


@dcs.dataclass(frozen=True, kw_only=True, slots=True)
class S3Dump:
    root_ref: s3_types.S3Ref
    parts: tuple[S3Part, ...]
    data_format: core.AbstractFileFormat
    rows: int
    bytes: int
    manifest_urls: dict[str, str]  # NOTE: when 3.15 switch to frozendict

    def get_manifest_url(self) -> str:
        if len(self.manifest_urls) != 1 or "_" not in self.manifest_urls:
            raise ValueError("the dump was made without a single manifestor")
        return self.manifest_urls["_"]


class ArrowToS3PartedParquetStreamDumper:
    def __init__(
        self,
        *,
        arrow_schema: pa.Schema,
        s3_region: str,
        s3_root_ref: s3_types.S3Ref,
        compression: str = "snappy",
        s3_part_mib: int = 256,
        s3_part_name_tpl: str = "part-{part_no:05d}.parquet",
        manifestors: cabc.Mapping[str, ManifestorProto] | ManifestorProto | None = None,
        heartbeat: cabc.Callable[[], None] | None = None,
        logger_factory: core.LoggerFactory = logging.getLogger,
    ) -> None:
        self._arrow_schema = arrow_schema
        self._s3_region = s3_region
        self._s3fs = pafs.S3FileSystem(region=s3_region)
        self._root_s3ref = s3_root_ref
        self._s3_part_bytes = s3_part_mib * c.BYTES_PER_MEBIBYTE
        self._heartbeat = heartbeat
        self._compression = compression
        self._s3_part_name_tpl = s3_part_name_tpl
        self._manifestors: dict[str, ManifestorProto] = {}
        if isinstance(manifestors, cabc.Mapping):
            self._manifestors = dict(manifestors)
        elif manifestors:
            self._manifestors = {"_": manifestors}
        self._log = logger_factory(__name__)

    def _write_part(
        self,
        batches: cabc.Iterator[pa.RecordBatch],
        *,
        pending: pa.RecordBatch | None,
        part_no: int,
    ) -> tuple[S3Part, pa.RecordBatch | None]:
        s3_ref = self._root_s3ref.make_child(
            self._s3_part_name_tpl.format(part_no=part_no),
        )
        rows = 0
        with self._s3fs.open_output_stream(s3_ref.path) as s3_sink:
            with pq.ParquetWriter(
                where=s3_sink,
                schema=self._arrow_schema,
                compression=self._compression,
            ) as s3_part_writer:
                while pending is not None:
                    if self._heartbeat is not None:
                        self._heartbeat()
                    s3_part_writer.write_batch(batch=pending)
                    rows += pending.num_rows
                    pending = next(batches, None)
                    if s3_sink.tell() >= self._s3_part_bytes:
                        break
            # the parquet footer is written when the writer closes
            size_bytes = s3_sink.tell()
        return S3Part(ref=s3_ref, bytes=size_bytes, rows=rows), pending

    def _write_parts(
        self,
        batches: cabc.Iterable[pa.RecordBatch],
    ) -> tuple[S3Part, ...]:
        s3_parts: list[S3Part] = []
        batches = iter(batches)
        pending = next(batches, None)
        while pending is not None:
            s3_part, pending = self._write_part(
                batches,
                pending=pending,
                part_no=len(s3_parts) + 1,
            )
            s3_parts.append(s3_part)
            self._log.info(
                f"Wrote {s3_part.ref.name} ({s3_part.bytes / c.BYTES_PER_MEBIBYTE:.0f}MiB)",
            )
        return tuple(s3_parts)

    def _write_manifest(
        self,
        manifestor: ManifestorProto,
        s3_parts: cabc.Iterable[S3Part],
    ) -> str:
        manifest_ref = self._root_s3ref.make_child(manifestor.filename)
        with self._s3fs.open_output_stream(manifest_ref.path) as sink:
            sink.write(manifestor.make_body(s3_parts))
        return manifest_ref.url

    def stream_batches_to_s3(
        self,
        batches: cabc.Iterable[pa.RecordBatch],
    ) -> S3Dump | None:
        parts = self._write_parts(batch for batch in batches if batch.num_rows)
        if not parts:
            return None

        manifest_urls = {
            name: self._write_manifest(manifestor, parts)
            for name, manifestor in self._manifestors.items()
        }

        return S3Dump(
            root_ref=self._root_s3ref,
            parts=parts,
            data_format=core.ParquetFormat(),
            rows=sum(part.rows for part in parts),
            bytes=sum(part.bytes for part in parts),
            manifest_urls=manifest_urls,
        )

    def _batch_rows(
        self,
        rows: cabc.Iterable[t.Any],
        *,
        arrow_batch_rows: int | None,
    ) -> cabc.Iterator[pa.RecordBatch]:
        probe_rows, batch_bytes = 1_000, 16 * c.BYTES_PER_MEBIBYTE
        struct_type = pa.struct(list(self._arrow_schema))
        chunk_rows = arrow_batch_rows or probe_rows
        rows = iter(rows)
        chunk = list(itertools.islice(rows, chunk_rows))
        while chunk:
            batch = pa.RecordBatch.from_struct_array(pa.array(chunk, type=struct_type))
            yield batch
            bytes_per_row = batch.nbytes / len(chunk)
            chunk_rows = arrow_batch_rows or max(1, int(batch_bytes / bytes_per_row))
            chunk = list(itertools.islice(rows, chunk_rows))

    def stream_dicts_to_s3(
        self,
        rows: cabc.Iterable[cabc.Mapping[str, t.Any]],
        *,
        arrow_batch_rows: int | None = None,
    ) -> S3Dump | None:
        return self.stream_batches_to_s3(
            self._batch_rows(rows, arrow_batch_rows=arrow_batch_rows),
        )

    def stream_items_to_s3(
        self,
        rows: cabc.Iterable[tuple[t.Any, ...]],
        *,
        arrow_batch_rows: int | None = None,
    ) -> S3Dump | None:
        return self.stream_batches_to_s3(
            self._batch_rows(rows, arrow_batch_rows=arrow_batch_rows),
        )

    def cleanup_root(self, *, suppress_error: bool = False) -> bool:
        return cleanup_subtree(
            self._root_s3ref,
            s3_region=self._s3_region,
            suppress_error=suppress_error,
        )
