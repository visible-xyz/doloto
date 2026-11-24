# doloto

A chisel for data engineering

## Status

Alpha: API changes without notice until 1.0.

## Installation

```bash
pip install doloto                              # core
pip install "doloto[backend-arrow]"             # + pyarrow: Arrow backend
pip install "doloto[backend-redshift]"          # + boto3: Redshift backend
pip install "doloto[bridge-arrow-to-s3]"        # + pyarrow: Arrow → S3
pip install "doloto[executor-psycopg]"          # + psycopg: psycopg 3 executor
pip install "doloto[executor-psycopg-binary]"   # + psycopg[binary]: psycopg 3 executor
pip install "doloto[executor-psycopg2]"         # + psycopg2: psycopg2 executor
pip install "doloto[executor-psycopg2-binary]"  # + psycopg2-binary: psycopg2 executor
```

## Layout

- `core`, `datatypes`: declarative schema core
- `families/`: capability-family primitives (sql, s3)
- `backends/`: per-technology backends (pg, redshift, arrow)
- `bridges/`: data movers (arrow → s3)
- `extensions/`: reusable scenarios composed from primitives

Library ships composable primitives; orchestration belongs to the consumer.
Extensions depend only on layers below (never on other extensions) and stay
free of file I/O and resources: they take parsed data, executors and
callables, and report progress through callbacks.

## License

BSD-3-Clause
