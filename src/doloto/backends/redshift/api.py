from __future__ import annotations

import dataclasses as dcs
import functools
import json
import typing as t

import boto3
from sqlglot import expressions as exp

from doloto import core
from doloto import exceptions as dl_excs
from doloto.backends.redshift import _tools
from doloto.backends.redshift import exceptions as excs
from doloto.families.s3 import types as s3_types
from doloto.families.sql import glot
from doloto.families.sql import types as sql_types
from doloto.families.sql._tools import aggr
from doloto.families.sql._tools import loading
from doloto.families.sql._tools import merge_rows
from doloto.families.sql._tools import table_ddl
from doloto.families.sql._tools import view_ddl


if t.TYPE_CHECKING:
    from collections import abc as cabc


UNLOAD_MANIFEST_OBJECT_NAME: t.Final[str] = "manifest"
MAX_VARCHAR_CHAR_LENGTH: t.Final[int] = (
    _tools.MAX_VARCHAR_BYTES // _tools.UTF8_MAX_BYTES_PER_CHAR
)


# ---------------------------------------------------------------------------
# Validations
# ---------------------------------------------------------------------------


def validate_table_name(table_name: str) -> None:
    _tools.validate_ident("table name", table_name)


def validate_schema_name(schema_name: str) -> None:
    _tools.validate_ident("schema name", schema_name)


# ---------------------------------------------------------------------------
# Catalog introspection
# ---------------------------------------------------------------------------


def list_schemas(query_executor: sql_types.QueryExecutor) -> tuple[str, ...]:
    rows = query_executor("""
        SELECT schema_name
        FROM information_schema.schemata
        ORDER BY schema_name
    """)
    return tuple(row["schema_name"] for row in rows)


# ---------------------------------------------------------------------------
# Full Table Management
# ---------------------------------------------------------------------------


def list_tables(
    query_executor: sql_types.QueryExecutor,
    *,
    db_schema: str,
) -> tuple[str, ...]:
    # pg_class, not svv_tables: svv hides relations the user has no privileges on
    rows = query_executor(f"""
        SELECT c.relname AS table_name
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = {_tools.quote_literal(db_schema)}
          AND c.relkind = 'r'
        ORDER BY c.relname
    """)
    return tuple(row["table_name"] for row in rows)


def table_stats(
    query_executor: sql_types.QueryExecutor,
    *,
    db_schema: str,
    db_table: str,
    count_rows: bool = False,
    count_null_columns: str | cabc.Iterable[str] | None = None,
    count_distinct_columns: str | cabc.Iterable[str] | None = None,
    min_columns: str | cabc.Iterable[str] | None = None,
    max_columns: str | cabc.Iterable[str] | None = None,
    sum_columns: str | cabc.Iterable[str] | None = None,
    avg_columns: str | cabc.Iterable[str] | None = None,
) -> sql_types.TableStats:
    return aggr.table_stats(
        query_executor,
        db_schema=db_schema,
        db_table=db_table,
        dialect=sql_types.Dialects.REDSHIFT,
        count_rows=count_rows,
        count_null_columns=count_null_columns,
        count_distinct_columns=count_distinct_columns,
        min_columns=min_columns,
        max_columns=max_columns,
        sum_columns=sum_columns,
        avg_columns=avg_columns,
    )


def has_table(
    query_executor: sql_types.QueryExecutor,
    *,
    db_schema: str,
    db_table: str,
) -> bool:
    # pg_class, not svv_tables: svv hides relations the user has no privileges on
    rows = query_executor(f"""
        SELECT COUNT(*) AS tables_count
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = {_tools.quote_literal(db_schema)}
          AND c.relname = {_tools.quote_literal(db_table)}
          AND c.relkind = 'r'
    """)
    return bool(rows[0]["tables_count"])


def create_table(
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    db_schema: str,
    schema_spec: core.SchemaSpec,
    db_table: str | None = None,
    if_not_exists: bool = False,
) -> None:
    ddl = table_ddl.render_create_table(
        db_schema=db_schema,
        db_table=db_table or schema_spec.name,
        schema_spec=schema_spec,
        render_colspec=_tools.colspec_to_sql,
        dialect=sql_types.Dialects.REDSHIFT,
        if_not_exists=if_not_exists,
    )
    stmt_executor(ddl)


def create_table_if_not_exists(
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    db_schema: str,
    schema_spec: core.SchemaSpec,
    db_table: str | None = None,
) -> None:
    create_table(
        stmt_executor,
        db_schema=db_schema,
        db_table=db_table,
        schema_spec=schema_spec,
        if_not_exists=True,
    )


def recreate_table(
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    db_schema: str,
    schema_spec: core.SchemaSpec,
    db_table: str | None = None,
    drop_cascade: bool = False,
) -> None:
    db_table = db_table or schema_spec.name
    drop_table(
        stmt_executor,
        db_schema=db_schema,
        db_table=db_table,
        if_exists=True,
        cascade=drop_cascade,
    )
    create_table(
        stmt_executor,
        db_schema=db_schema,
        db_table=db_table,
        schema_spec=schema_spec,
    )


def drop_table(
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    db_schema: str,
    db_table: str,
    if_exists: bool = False,
    cascade: bool = False,
) -> None:
    ddl = table_ddl.render_drop_table(
        db_schema=db_schema,
        db_table=db_table,
        dialect=sql_types.Dialects.REDSHIFT,
        if_exists=if_exists,
        cascade=cascade,
    )
    stmt_executor(ddl)


def drop_table_if_exists(
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    db_schema: str,
    db_table: str,
    cascade: bool = False,
) -> None:
    drop_table(
        stmt_executor,
        db_schema=db_schema,
        db_table=db_table,
        if_exists=True,
        cascade=cascade,
    )


def rename_table(
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    db_schema: str,
    src_table_name: str,
    dst_table_name: str,
) -> None:
    ddl = table_ddl.render_rename_table(
        db_schema=db_schema,
        src_table_name=src_table_name,
        dst_table_name=dst_table_name,
        dialect=sql_types.Dialects.REDSHIFT,
    )
    stmt_executor(ddl)


def move_table(
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    db_schema: str,
    src_table_name: str,
    dst_table_name: str,
    replace: bool = False,
    drop_cascade: bool = False,
) -> None:
    if replace:
        drop_table(
            stmt_executor,
            db_schema=db_schema,
            db_table=dst_table_name,
            if_exists=True,
            cascade=drop_cascade,
        )
    rename_table(
        stmt_executor,
        db_schema=db_schema,
        src_table_name=src_table_name,
        dst_table_name=dst_table_name,
    )


# ---------------------------------------------------------------------------
# Full View Management
# ---------------------------------------------------------------------------


def create_view(
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    db_schema: str,
    view_name: str,
    select: exp.Expression,
    no_schema_binding: bool = True,
    comment: str | None = None,
) -> None:
    # late binding by default: bound views block the move/recreate table
    # management this backend is built around
    create = exp.Create(
        this=exp.table_(view_name, db=db_schema),
        kind="VIEW",
        expression=select,
        no_schema_binding=no_schema_binding,
    )
    stmt_executor(create.sql(dialect=sql_types.Dialects.REDSHIFT, identify=True))
    if comment:
        comment_on_view(
            stmt_executor,
            db_schema=db_schema,
            view_name=view_name,
            comment=comment,
        )


def drop_view(
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    db_schema: str,
    view_name: str,
    if_exists: bool = False,
    cascade: bool = False,
) -> None:
    ddl = view_ddl.render_drop_view(
        db_schema=db_schema,
        view_name=view_name,
        dialect=sql_types.Dialects.REDSHIFT,
        if_exists=if_exists,
        cascade=cascade,
    )
    stmt_executor(ddl)


def drop_view_if_exists(
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    db_schema: str,
    view_name: str,
    cascade: bool = False,
) -> None:
    drop_view(
        stmt_executor,
        db_schema=db_schema,
        view_name=view_name,
        if_exists=True,
        cascade=cascade,
    )


def recreate_view(
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    db_schema: str,
    view_name: str,
    select: exp.Expression,
    no_schema_binding: bool = True,
    comment: str | None = None,
) -> None:
    # not CREATE OR REPLACE: it can only append view columns, while a
    # drop+create applies any column change deterministically
    drop_view(
        stmt_executor,
        db_schema=db_schema,
        view_name=view_name,
        if_exists=True,
    )
    create_view(
        stmt_executor,
        db_schema=db_schema,
        view_name=view_name,
        select=select,
        no_schema_binding=no_schema_binding,
        comment=comment,
    )


# ---------------------------------------------------------------------------
# View comments
# ---------------------------------------------------------------------------


def comment_on_view(
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    db_schema: str,
    view_name: str,
    comment: str,
) -> None:
    ddl = view_ddl.render_comment_on_view(
        db_schema=db_schema,
        view_name=view_name,
        comment=comment,
        dialect=sql_types.Dialects.REDSHIFT,
    )
    stmt_executor(ddl)


def load_view_comments(
    query_executor: sql_types.QueryExecutor,
    *,
    db_schema: str,
) -> dict[str, str | None]:
    rows = query_executor(f"""
        SELECT v.viewname, d.description
        FROM pg_views v
        JOIN pg_class c ON c.relname = v.viewname
        JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = v.schemaname
        LEFT JOIN pg_description d ON d.objoid = c.oid AND d.objsubid = 0
        WHERE v.schemaname = {_tools.quote_literal(db_schema)}
    """)
    return {row["viewname"]: row["description"] for row in rows}


# ---------------------------------------------------------------------------
# Patch table schema
# ---------------------------------------------------------------------------


def reduce_table_to_spec(
    query_executor: sql_types.QueryExecutor,
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    db_schema: str,
    schema_spec: core.SchemaSpec,
    db_table: str | None = None,
    overrides: cabc.Iterable[core.ColumnOverride] | None = None,
    strict: bool = True,
) -> tuple[str, ...]:
    db_table = db_table or schema_spec.name
    actual_spec = load_schema_spec(
        query_executor,
        db_schema=db_schema,
        db_table=db_table,
        overrides=overrides,
        allow_missing=not strict,
    )
    if not actual_spec:
        return ()
    diff = schema_spec.compare(actual_spec)
    if diff is None:
        return ()
    if strict and (diff.is_incompatible or diff.missing):
        raise excs.CantReduceTableExc(
            db_schema=db_schema,
            db_table=db_table,
            reason=f"not only extra columns: {diff}",
        )

    extra_column_names = tuple(colspec.name for colspec in diff.extra)
    # Redshift accepts a single DROP COLUMN per ALTER TABLE statement
    for column_name in extra_column_names:
        column = exp.column(column_name)
        # TODO: drop `this=` once sqlglot < 30 is unsupported (`tables=` since 30)
        drop = exp.Drop(this=column, tables=[column.copy()], kind="COLUMN")
        alter = exp.Alter(
            this=exp.table_(db_table, db=db_schema),
            kind="TABLE",
            actions=[drop],
        )
        stmt_executor(alter.sql(dialect=sql_types.Dialects.REDSHIFT, identify=True))
    return extra_column_names


# ---------------------------------------------------------------------------
# Rows merging
# ---------------------------------------------------------------------------


def replace_all_rows(  # within single transaction
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    db_schema: str,
    src_table_name: str,
    dst_table_name: str,
    column_names: cabc.Iterable[str],
) -> None:
    merge_rows.replace_all_rows(
        stmt_executor,
        db_schema=db_schema,
        src_table_name=src_table_name,
        dst_table_name=dst_table_name,
        column_names=column_names,
        dialect=sql_types.Dialects.REDSHIFT,
    )


def merge_rows_by__primary_key(
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    db_schema: str,
    src_table_name: str,
    dst_table_name: str,
    pk_columns: cabc.Iterable[str],
    data_columns: cabc.Iterable[str],
) -> None:
    # MERGE INTO "s"."dst" USING "s"."src"
    #      ON "s"."dst"."pk" = "s"."src"."pk"
    #    WHEN MATCHED THEN UPDATE SET "col" = "s"."src"."col"
    #    WHEN NOT MATCHED THEN INSERT ("pk", "col")
    #                          VALUES ("s"."src"."pk", "s"."src"."col")
    #
    #
    # the MATCHED branch is dropped when every column belongs to the key
    pk_cols, data_cols = tuple(pk_columns), tuple(data_columns)
    dl_excs.EmptyValueExc.validate(pk_cols, label="PK columns")

    # NOT MATCHED branch: INSERT
    when_branches = [
        exp.When(
            matched=False,
            then=exp.Insert(
                this=exp.Tuple(  # (...) — target columns
                    expressions=glot.project(pk_cols + data_cols),
                ),
                expression=exp.Tuple(  # VALUES (...) — source columns
                    expressions=glot.project(
                        pk_cols + data_cols,
                        db_schema=db_schema,
                        table_name=src_table_name,
                    ),
                ),
            ),
        ),
    ]
    # MATCHED branch: UPDATE
    if data_cols:
        assignments = [
            exp.EQ(this=target, expression=source)
            for target, source in zip(
                glot.project(data_cols),
                glot.project(
                    data_cols,
                    db_schema=db_schema,
                    table_name=src_table_name,
                ),
                strict=True,
            )
        ]
        when_branches.append(
            exp.When(matched=True, then=exp.Update(expressions=assignments)),
        )

    pk_matches = [
        target.eq(source)
        for target, source in zip(
            glot.project(
                pk_columns,
                db_schema=db_schema,
                table_name=dst_table_name,
            ),
            glot.project(
                pk_columns,
                db_schema=db_schema,
                table_name=src_table_name,
            ),
            strict=True,
        )
    ]
    statement = exp.Merge(
        this=exp.table_(dst_table_name, db=db_schema),
        using=exp.table_(src_table_name, db=db_schema),
        on=exp.and_(*pk_matches),
        whens=exp.Whens(expressions=when_branches),
    )

    stmt_executor(statement.sql(dialect=sql_types.Dialects.REDSHIFT, identify=True))


def merge_rows_by__max_version(
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    db_schema: str,
    src_table_name: str,
    dst_table_name: str,
    pk_columns: cabc.Iterable[str],
    data_columns: cabc.Iterable[str],
    version_column: str,
) -> None:
    # DELETE FROM "s"."dst" USING "s"."src"
    #      WHERE "s"."dst"."pk" = "s"."src"."pk"
    #        AND "s"."dst"."ver" <= "s"."src"."ver"
    # INSERT INTO "s"."dst" ("pk", "col")
    #      SELECT "pk", "col" FROM "s"."src"
    #       WHERE NOT EXISTS (
    #             SELECT 1 FROM "s"."dst" WHERE "s"."dst"."pk" = "s"."src"."pk")
    pk_cols, data_cols = tuple(pk_columns), tuple(data_columns)
    dl_excs.EmptyValueExc.validate(pk_cols, label="PK columns")

    dst_table = exp.table_(dst_table_name, db=db_schema)
    src_table = exp.table_(src_table_name, db=db_schema)

    dst_version = exp.column(version_column, table=dst_table_name, db=db_schema)
    src_version = exp.column(version_column, table=src_table_name, db=db_schema)

    pk_matches = [
        target.eq(source)
        for target, source in zip(
            glot.project(pk_cols, db_schema=db_schema, table_name=dst_table_name),
            glot.project(pk_cols, db_schema=db_schema, table_name=src_table_name),
            strict=True,
        )
    ]

    # the source wins ties, so re-inserted rows carry the newest version
    outdated = exp.and_(*pk_matches, exp.LTE(this=dst_version, expression=src_version))
    delete = exp.Delete(
        this=dst_table,
        using=[src_table],
        where=exp.Where(this=outdated),
    )

    missing_in_dst = exp.Not(
        this=exp.Exists(
            this=exp.select(exp.Literal.number(1))
            .from_(dst_table.copy())
            .where(exp.and_(*pk_matches)),
        ),
    )
    insert = exp.insert(
        exp.select(*glot.project(pk_cols + data_cols))
        .from_(src_table.copy())
        .where(missing_in_dst),
        into=dst_table.copy(),
        columns=pk_cols + data_cols,
    )

    stmt_executor(delete.sql(dialect=sql_types.Dialects.REDSHIFT, identify=True))
    stmt_executor(insert.sql(dialect=sql_types.Dialects.REDSHIFT, identify=True))


# ---------------------------------------------------------------------------
# S3 Integrations
# ---------------------------------------------------------------------------


@dcs.dataclass(frozen=True, kw_only=True, slots=True)
class RedshiftS3CopyManifestor:
    filename: str = "manifest-redshift.json"

    def make_body(self, s3_objects: cabc.Iterable[s3_types.S3ObjectProto]) -> bytes:
        entries = [
            dict(
                url=s3_object.ref.url,
                meta=dict(content_length=s3_object.bytes),
                mandatory=True,
            )
            for s3_object in s3_objects
        ]
        return json.dumps(dict(entries=entries)).encode()


def copy_from_s3(
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    db_schema: str,
    db_table: str,
    s3_url: str | s3_types.S3Ref,
    iam_role_arn: str,
    data_format: core.AbstractFileFormat,
    substitute_invalid_chars_with: str | None = None,
    manifest: bool = False,
    statupdate: bool | None = None,
) -> None:
    copy_table = exp.Table(
        this=exp.Identifier(this=db_table, quoted=True),
        db=exp.Identifier(this=db_schema, quoted=True),
    )
    clauses = [
        f"COPY {copy_table.sql(dialect=sql_types.Dialects.REDSHIFT)}",
        f"FROM {_tools.quote_literal(str(s3_url))}",
        f"IAM_ROLE {_tools.quote_literal(iam_role_arn)}",
        *_tools.copy_format_clauses(data_format),
    ]

    if substitute_invalid_chars_with is not None:
        clauses.append(
            f"ACCEPTINVCHARS AS {_tools.quote_literal(substitute_invalid_chars_with)}",
        )

    if manifest:
        clauses.append("MANIFEST")

    if statupdate:
        clauses.append("STATUPDATE ON")
    elif statupdate is False:
        clauses.append("STATUPDATE OFF")

    stmt_executor("\n".join(clauses))


def stage_from_s3_by__recreate(
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    db_schema: str,
    stage_table: str,
    schema_spec: core.SchemaSpec,
    s3_url: str | s3_types.S3Ref,
    iam_role_arn: str,
    data_format: core.AbstractFileFormat,
    substitute_invalid_chars_with: str | None = None,
    manifest: bool,
) -> None:
    recreate_table(
        stmt_executor,
        db_schema=db_schema,
        db_table=stage_table,
        schema_spec=schema_spec,
    )
    copy_from_s3(
        stmt_executor,
        db_schema=db_schema,
        db_table=stage_table,
        s3_url=s3_url,
        iam_role_arn=iam_role_arn,
        data_format=data_format,
        substitute_invalid_chars_with=substitute_invalid_chars_with,
        manifest=manifest,
        statupdate=False,
    )


# ---------------------------------------------------------------------------
# UNLOAD to S3
# ---------------------------------------------------------------------------


@dcs.dataclass(frozen=True, kw_only=True, slots=True)
class UnloadManifestEntry:
    ref: s3_types.S3Ref
    bytes: int

    @classmethod
    def from_json(cls, entry: dict[str, t.Any]) -> t.Self:
        return cls(
            ref=s3_types.S3Ref.from_url(entry["url"]),
            bytes=entry["meta"]["content_length"],
        )


@dcs.dataclass(frozen=True, kw_only=True, slots=True)
class VerboseUnloadManifestEntry(UnloadManifestEntry):
    rows: int

    @classmethod
    def from_json(cls, entry: dict[str, t.Any]) -> t.Self:
        return cls(
            ref=s3_types.S3Ref.from_url(entry["url"]),
            bytes=entry["meta"]["content_length"],
            rows=entry["meta"]["record_count"],
        )


@dcs.dataclass(frozen=True, kw_only=True, slots=True)
class UnloadManifest:
    ref: s3_types.S3Ref
    entries: tuple[UnloadManifestEntry, ...]

    @property
    def files(self) -> int:
        return len(self.entries)

    @property
    def bytes(self) -> int:
        return sum(entry.bytes for entry in self.entries)


@dcs.dataclass(frozen=True, kw_only=True, slots=True)
class VerboseUnloadManifest(UnloadManifest):
    entries: tuple[VerboseUnloadManifestEntry, ...]

    @property
    def rows(self) -> int:
        return sum(entry.rows for entry in self.entries)


def unload_to_s3_by__parts(
    stmt_executor: sql_types.QueryExecutorWithoutResult,
    *,
    select: exp.Expression,
    s3_prefix_url: str | s3_types.S3Ref,
    iam_role_arn: str,
    data_format: core.AbstractFileFormat,
    max_file_size_mb: int | None = None,
    manifest: bool | t.Literal["verbose"] = True,
    region: str | None = None,
) -> None:
    dst_ref = s3_types.refify_url(s3_prefix_url)
    query = select.sql(dialect=sql_types.Dialects.REDSHIFT, identify=True)
    clauses = [
        f"UNLOAD ({_tools.quote_literal(query)})",
        f"TO {_tools.quote_literal(dst_ref.slashed_url)}",
        f"IAM_ROLE {_tools.quote_literal(iam_role_arn)}",
        *_tools.unload_format_clauses(data_format),
        f"EXTENSION {_tools.quote_literal(data_format.filename_extension)}",
    ]

    if max_file_size_mb is not None:
        clauses.append(f"MAXFILESIZE {max_file_size_mb} MB")

    if manifest == "verbose":
        clauses.append("MANIFEST VERBOSE")
    elif manifest:
        clauses.append("MANIFEST")

    if region:
        clauses.append(f"REGION {_tools.quote_literal(region)}")

    stmt_executor("\n".join(clauses))


@t.overload
def read_s3_unload_manifest(
    prefix_url: str | s3_types.S3Ref,
    *,
    region: str,
    verbose_manifest: t.Literal[True],
    raise_if_missing: t.Literal[True],
) -> VerboseUnloadManifest: ...


@t.overload
def read_s3_unload_manifest(
    prefix_url: str | s3_types.S3Ref,
    *,
    region: str,
    verbose_manifest: t.Literal[True],
    raise_if_missing: t.Literal[False] = False,
) -> VerboseUnloadManifest | None: ...


@t.overload
def read_s3_unload_manifest(
    prefix_url: str | s3_types.S3Ref,
    *,
    region: str,
    verbose_manifest: t.Literal[False],
    raise_if_missing: t.Literal[True],
) -> UnloadManifest: ...


@t.overload
def read_s3_unload_manifest(
    prefix_url: str | s3_types.S3Ref,
    *,
    region: str,
    verbose_manifest: t.Literal[False],
    raise_if_missing: t.Literal[False] = False,
) -> UnloadManifest | None: ...


@t.overload
def read_s3_unload_manifest(
    prefix_url: str | s3_types.S3Ref,
    *,
    region: str,
    verbose_manifest: t.Literal["auto"] = "auto",
    raise_if_missing: t.Literal[True],
) -> UnloadManifest | VerboseUnloadManifest: ...


@t.overload
def read_s3_unload_manifest(
    prefix_url: str | s3_types.S3Ref,
    *,
    region: str,
    verbose_manifest: t.Literal["auto"] = "auto",
    raise_if_missing: t.Literal[False] = False,
) -> UnloadManifest | VerboseUnloadManifest | None: ...


def read_s3_unload_manifest(
    prefix_url: str | s3_types.S3Ref,
    *,
    region: str,
    verbose_manifest: bool | t.Literal["auto"] = "auto",
    raise_if_missing: bool = False,
) -> UnloadManifest | VerboseUnloadManifest | None:
    manifest_ref = s3_types.refify_url(prefix_url).make_child(
        UNLOAD_MANIFEST_OBJECT_NAME,
    )
    s3 = boto3.client("s3", region_name=region)
    try:
        resp = s3.get_object(Bucket=manifest_ref.bucket, Key=manifest_ref.key)
    except s3.exceptions.NoSuchKey:
        # an UNLOAD with no rows writes nothing, the manifest included
        if raise_if_missing:
            raise
        return None
    entries = json.load(resp["Body"])["entries"]
    if verbose_manifest == "auto":
        verbose_manifest = bool(entries) and "record_count" in entries[0]["meta"]
    if verbose_manifest:
        return VerboseUnloadManifest(
            ref=manifest_ref,
            entries=tuple(map(VerboseUnloadManifestEntry.from_json, entries)),
        )
    return UnloadManifest(
        ref=manifest_ref,
        entries=tuple(map(UnloadManifestEntry.from_json, entries)),
    )


# ---------------------------------------------------------------------------
# Doloto Schema / Column Specs
# ---------------------------------------------------------------------------


@t.overload
def load_schema_spec(
    query_executor: sql_types.QueryExecutor,
    *,
    db_schema: str,
    db_table: str,
    name: str | None = None,
    columns: cabc.Iterable[str] | None = None,
    overrides: cabc.Iterable[core.ColumnOverride] | None = None,
    allow_missing: t.Literal[False],
    backend_types: sql_types.BackendTypesPolicy = sql_types.BackendTypesPolicy.FALLBACK,
) -> core.SchemaSpec: ...


@t.overload
def load_schema_spec(
    query_executor: sql_types.QueryExecutor,
    *,
    db_schema: str,
    db_table: str,
    name: str | None = None,
    columns: cabc.Iterable[str] | None = None,
    overrides: cabc.Iterable[core.ColumnOverride] | None = None,
    allow_missing: t.Literal[True] = True,
    backend_types: sql_types.BackendTypesPolicy = sql_types.BackendTypesPolicy.FALLBACK,
) -> core.SchemaSpec | None: ...


@t.overload
def load_schema_spec(
    query_executor: sql_types.QueryExecutor,
    *,
    db_schema: str,
    db_table: str,
    name: str | None = None,
    columns: cabc.Iterable[str] | None = None,
    overrides: cabc.Iterable[core.ColumnOverride] | None = None,
    allow_missing: bool,
    backend_types: sql_types.BackendTypesPolicy = sql_types.BackendTypesPolicy.FALLBACK,
) -> core.SchemaSpec | None: ...


def load_schema_spec(
    query_executor: sql_types.QueryExecutor,
    *,
    db_schema: str,
    db_table: str,
    name: str | None = None,
    columns: cabc.Iterable[str] | None = None,
    overrides: cabc.Iterable[core.ColumnOverride] | None = None,
    allow_missing: bool = True,
    backend_types: sql_types.BackendTypesPolicy = sql_types.BackendTypesPolicy.FALLBACK,
) -> core.SchemaSpec | None:
    request: sql_types.SchemaLoadRequest = db_table
    if columns:
        request = (db_table, columns)
    specs = load_schema_specs(
        query_executor,
        db_schema=db_schema,
        db_tables=(request,),
        overrides={db_table: overrides or ()},
        allow_missing=allow_missing,
        backend_types=backend_types,
    )
    schema_spec = specs[db_table]
    if schema_spec and name:
        return schema_spec.renamed(name)
    return schema_spec


@t.overload
def load_schema_specs(
    query_executor: sql_types.QueryExecutor,
    *,
    db_schema: str,
    db_tables: cabc.Iterable[sql_types.SchemaLoadRequest],
    overrides: cabc.Mapping[str, cabc.Iterable[core.ColumnOverride]] | None = None,
    aliases: cabc.Mapping[str, cabc.Mapping[str, str]] | None = None,
    allow_missing: t.Literal[False],
    backend_types: sql_types.BackendTypesPolicy = sql_types.BackendTypesPolicy.FALLBACK,
) -> dict[str, core.SchemaSpec]: ...


@t.overload
def load_schema_specs(
    query_executor: sql_types.QueryExecutor,
    *,
    db_schema: str,
    db_tables: cabc.Iterable[sql_types.SchemaLoadRequest],
    overrides: cabc.Mapping[str, cabc.Iterable[core.ColumnOverride]] | None = None,
    aliases: cabc.Mapping[str, cabc.Mapping[str, str]] | None = None,
    allow_missing: t.Literal[True] = True,
    backend_types: sql_types.BackendTypesPolicy = sql_types.BackendTypesPolicy.FALLBACK,
) -> dict[str, core.SchemaSpec | None]: ...


@t.overload
def load_schema_specs(
    query_executor: sql_types.QueryExecutor,
    *,
    db_schema: str,
    db_tables: cabc.Iterable[sql_types.SchemaLoadRequest],
    overrides: cabc.Mapping[str, cabc.Iterable[core.ColumnOverride]] | None = None,
    aliases: cabc.Mapping[str, cabc.Mapping[str, str]] | None = None,
    allow_missing: bool,
    backend_types: sql_types.BackendTypesPolicy = sql_types.BackendTypesPolicy.FALLBACK,
) -> dict[str, core.SchemaSpec] | dict[str, core.SchemaSpec | None]: ...


def load_schema_specs(
    query_executor: sql_types.QueryExecutor,
    *,
    db_schema: str,
    db_tables: cabc.Iterable[sql_types.SchemaLoadRequest],
    overrides: cabc.Mapping[str, cabc.Iterable[core.ColumnOverride]] | None = None,
    aliases: cabc.Mapping[str, cabc.Mapping[str, str]] | None = None,
    allow_missing: bool = True,
    backend_types: sql_types.BackendTypesPolicy = sql_types.BackendTypesPolicy.FALLBACK,
) -> dict[str, core.SchemaSpec] | dict[str, core.SchemaSpec | None]:
    sql_types.BackendTypesPolicy(backend_types)  # fails on a non-member
    table_to_columns = loading.make_table_to_columns(db_tables)
    rows = query_executor(f"""
        SELECT
            table_name
          , column_name AS name
          , data_type
          , character_maximum_length AS byte_length
          , numeric_precision AS precision
          , numeric_scale AS scale
          , (is_nullable = 'YES') AS nullable
        FROM svv_columns
        WHERE table_schema = {_tools.quote_literal(db_schema)}
          AND table_name IN ({_tools.quote_and_join_literals(*table_to_columns)})
        ORDER BY table_name, ordinal_position
    """)
    cols_by_table = loading.collect_column_specs(
        rows,
        db_schema=db_schema,
        db_tables=table_to_columns,
        overrides=overrides,
        make_colspec=functools.partial(
            _tools.make_column_spec_from_svv_row,
            backend_types=backend_types,
        ),
        allow_missing=allow_missing,
    )
    pks_by_table = _tools.load_primary_keys(
        query_executor,
        db_schema=db_schema,
        db_tables=table_to_columns,
    )
    specs = loading.build_schema_specs(
        cols_by_table=cols_by_table,
        pks_by_table=pks_by_table,
        db_schema=db_schema,
        db_tables=table_to_columns,
    )
    for db_table, renames in (aliases or {}).items():
        spec = specs.get(db_table)
        if spec is not None:
            specs[db_table] = spec.renamed_columns(renames)
    return specs
