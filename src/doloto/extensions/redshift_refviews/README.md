# redshift_refviews

Selective, consumer-facing read access to Redshift relations via managed
late-binding views ("refviews"). A refview is a loose reference: created
`WITH NO SCHEMA BINDING`, it survives the pipeline dropping/replacing the
relation underneath it — so producers (an ingest pipeline, a hash layer, …)
can keep rebuilding their tables while consumers read through stable views.

The extension is generic over the data source (each spec names its own source
schema and relation) and specific to Redshift (late-binding views). It carries
no notion of ingest tables, hashes, or the config vocabulary that decides what
to expose — the consumer builds the specs.

## Model

Source and destination are explicit on every spec: a refview reads one source
relation and materializes one view in a destination schema.

- `Refview` — a spec: a view (named by the manager's `namespace`/`tailmark`) to
  maintain in `dst_schema`, selecting `src_column_names` from the single source
  relation `src_schema.src_relation`. `no_schema_binding` (default `True`) makes
  it `WITH NO SCHEMA BINDING`; set it `False` for a schema-bound view that pins
  the source.

## Manager

`RefviewManager(namespace=, tailmark="refview")` holds the naming scheme;
`.reconcile(refviews, query_executor=, stmt_executor=)` reconciles the given
refviews, grouped by destination schema, and returns a `RefviewReconcileStats`
(`created`/`recreated`/`unchanged`/`dropped` counts):

- one `dst_schema.{namespace}__{src_relation}__{tailmark}` per spec,
  late-binding by default (`WITH NO SCHEMA BINDING`), selecting the given
  columns from `src_schema.src_relation`;
- `namespace` (mandatory) and `tailmark` (optional, default `refview`), with
  their `__` separators, are the distinctive literals that mark the managed
  views apart from foreign ones for garbage collection; both must be non-empty;
- unchanged views are skipped: each carries a
  `COMMENT ON VIEW ... 'refview_select_sha256=<hash>'` marker, recreated only
  when the desired view (SELECT plus binding mode) hashes differently (comment
  write is best-effort — a lost marker just costs one extra recreate);
- garbage collection is scoped, within each touched destination schema, to the
  names `view_name_tpl` could have produced (foreign objects are never
  dropped); a destination schema no longer fed any refview is not visited, so
  its stale refviews must be cleaned manually.

## Charter notes

Inputs are executors and `Refview` specs; the consumer decides which relations
and columns to expose and to which schemas.
Depends downward on `backends/redshift`; does not depend on other extensions.
