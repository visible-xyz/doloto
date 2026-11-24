import datetime as dtm
import enum
import functools
import re
import typing as t
import uuid

from miska import enums

from doloto._tools import immutables


_URL_PREFIX: t.Final[str] = "s3://"
_MAX_KEY_BYTES: t.Final[int] = 1024
_BUCKET_MIN_CHARS: t.Final[int] = 3
_BUCKET_MAX_CHARS: t.Final[int] = 255
_KEY_CHARS_TO_AVOID: t.Final[frozenset[str]] = frozenset('\\{}^%`[]"<>~#|')
_BUCKET_LAYOUT_RE: t.Final[re.Pattern[str]] = re.compile(
    r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]",
)
_BUCKET_IP_RE: t.Final[re.Pattern[str]] = re.compile(r"(\d{1,3}\.){3}\d{1,3}")
_MULTI_SLASH_RE: t.Final[re.Pattern[str]] = re.compile(r"/+")
_BUCKET_RESERVED_PREFIXES: t.Final[tuple[str, ...]] = (
    "xn--",
    "sthree-",
    "amzn-s3-demo-",
)
_BUCKET_RESERVED_SUFFIXES: t.Final[tuple[str, ...]] = (
    "-s3alias",
    "--ol-s3",
    "--x-s3",
    "--table-s3",
)


class Mode(enums.LowerCaseStrEnum):
    AWS = enum.auto()
    DOLOTO = enum.auto()


@functools.total_ordering
class S3Ref(immutables.Immutable):
    __slots__ = ("bucket", "key", "mode", "name", "path", "prefix", "url")

    name: str
    bucket: str
    prefix: str
    mode: Mode
    key: str
    path: str
    url: str

    def __init__(
        self,
        name: str,
        *,
        bucket: str,
        prefix: str = "",
        mode: Mode = Mode.DOLOTO,
    ) -> None:
        key = f"{prefix}{name}"
        path = f"{bucket}/{key}"
        self._set_attrs(
            name=name,
            bucket=bucket,
            prefix=prefix,
            mode=mode,
            key=key,
            path=path,
            url=f"{_URL_PREFIX}{path}",
        )
        if mode is Mode.AWS:
            self._validate_aws()
        elif mode is Mode.DOLOTO:
            self._validate_doloto()
        else:
            raise ValueError(f"unknown mode: {mode!r}")

    def _validate_aws(self) -> None:
        self._validate_attr_types()
        self._validate_bucket_slashes()
        self._validate_bucket_length()
        self._validate_name()
        self._validate_prefix()
        self._validate_key_length()

    def _validate_doloto(self) -> None:
        self._validate_aws()
        self._validate_bucket_alphabet()
        self._validate_bucket_dots()
        self._validate_bucket_ip()
        self._validate_bucket_reserved()
        self._validate_key_control_chars()
        self._validate_key_chars_to_avoid()
        self._validate_key_dot_segments()

    def _validate_attr_types(self) -> None:
        for label in ("name", "bucket", "prefix"):
            value = getattr(self, label)
            if not isinstance(value, str):
                raise TypeError(f"s3 ref {label} must be str, got {value!r}")

    def _validate_bucket_slashes(self) -> None:
        if "/" in self.bucket:
            raise ValueError(f"slash in s3 bucket name: {self.bucket!r}")

    def _validate_bucket_length(self) -> None:
        if not _BUCKET_MIN_CHARS <= len(self.bucket) <= _BUCKET_MAX_CHARS:
            raise ValueError(
                f"s3 bucket length must be"
                f" {_BUCKET_MIN_CHARS}..{_BUCKET_MAX_CHARS}: {self.bucket!r}",
            )

    def _validate_name(self) -> None:
        if not self.name or "/" in self.name:
            raise ValueError(f"invalid s3 object name: {self.name!r}")

    def _validate_prefix(self) -> None:
        if self.prefix and not self.prefix.endswith("/"):
            raise ValueError(
                f"s3 prefix must be empty or end with '/': {self.prefix!r}",
            )
        if self.prefix.startswith("/") or "//" in self.prefix:
            raise ValueError(f"invalid s3 prefix: {self.prefix!r}")

    def _validate_key_length(self) -> None:
        key_bytes = len(self.key.encode())
        if key_bytes > _MAX_KEY_BYTES:
            raise ValueError(
                f"s3 key is longer than {_MAX_KEY_BYTES} bytes: {key_bytes}",
            )

    def _validate_bucket_alphabet(self) -> None:
        if not _BUCKET_LAYOUT_RE.fullmatch(self.bucket):
            raise ValueError(f"non-compliant s3 bucket name: {self.bucket!r}")

    def _validate_bucket_dots(self) -> None:
        if ".." in self.bucket:
            raise ValueError(f"adjacent dots in s3 bucket name: {self.bucket!r}")

    def _validate_bucket_ip(self) -> None:
        if _BUCKET_IP_RE.fullmatch(self.bucket):
            raise ValueError(
                f"s3 bucket name looks like an ip address: {self.bucket!r}",
            )

    def _validate_bucket_reserved(self) -> None:
        if self.bucket.startswith(_BUCKET_RESERVED_PREFIXES):
            raise ValueError(f"reserved prefix in s3 bucket name: {self.bucket!r}")
        if self.bucket.endswith(_BUCKET_RESERVED_SUFFIXES):
            raise ValueError(f"reserved suffix in s3 bucket name: {self.bucket!r}")

    def _validate_key_control_chars(self) -> None:
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in self.key):
            raise ValueError(f"control character in s3 key: {self.key!r}")

    def _validate_key_chars_to_avoid(self) -> None:
        chars_to_avoid = _KEY_CHARS_TO_AVOID.intersection(self.key)
        if chars_to_avoid:
            raise ValueError(
                f"characters to avoid {sorted(chars_to_avoid)} in s3 key: {self.key!r}",
            )

    def _validate_key_dot_segments(self) -> None:
        for segment in self.key.split("/"):
            if segment in (".", ".."):
                raise ValueError(f"dot segment in s3 key: {self.key!r}")

    @property
    def _identity(self) -> tuple[str, str, str]:
        return (self.bucket, self.prefix, self.name)

    def __eq__(self, other: object) -> bool:
        if other.__class__ is not self.__class__:
            return NotImplemented
        return self._identity == other._identity

    def __lt__(self, other: object) -> bool:
        if other.__class__ is not self.__class__:
            return NotImplemented
        return self._identity < other._identity

    def __hash__(self) -> int:
        return hash(self._identity)

    def __contains__(self, ref: t.Self) -> bool:
        return ref.is_under(self)

    def __truediv__(self, relative_key: str) -> t.Self:
        return self.make_descendant(relative_key)

    def __copy__(self) -> t.Self:
        return self

    def __deepcopy__(self, memo: dict[int, t.Any]) -> t.Self:
        return self

    @classmethod
    def _from_tuple(
        cls,
        name: str,
        bucket: str,
        prefix: str,
        mode: Mode,
    ) -> t.Self:
        return cls(name, bucket=bucket, prefix=prefix, mode=mode)

    def _as_tuple(self) -> tuple[str, str, str, Mode]:
        return self.name, self.bucket, self.prefix, self.mode

    def __reduce__(self) -> tuple[t.Any, ...]:
        return self._from_tuple, self._as_tuple()

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}"
            f"({self.name!r}, bucket={self.bucket!r}, prefix={self.prefix!r},"
            f" mode={self.mode!r})"
        )

    def __str__(self) -> str:
        return self.url

    def as_kwargs(self) -> dict[str, t.Any]:
        return dict(
            name=self.name,
            bucket=self.bucket,
            prefix=self.prefix,
            mode=self.mode,
        )

    def as_dict(self) -> dict[str, t.Any]:
        return self.as_kwargs() | dict(
            key=self.key,
            path=self.path,
            url=self.url,
        )

    # Slashed forms

    @property
    def slashed_key(self) -> str:
        return f"{self.key}/"

    @property
    def slashed_path(self) -> str:
        return f"{self.path}/"

    @property
    def slashed_url(self) -> str:
        return f"{self.url}/"

    # Factories

    @classmethod
    def from_segments(
        cls,
        segment: str,
        *more_segments: str,
        bucket: str,
        mode: Mode = Mode.DOLOTO,
    ) -> t.Self:
        """Build from key segments; the last one is the object name.

        >>> S3Ref.from_segments("dumps", "daily", "part_00.parquet", bucket="my-bucket")
        s3://my-bucket/dumps/daily/part_00.parquet  (prefix "dumps/daily/")
        >>> S3Ref.from_segments("part_00.parquet", bucket="my-bucket")
        s3://my-bucket/part_00.parquet  (prefix "")
        """
        *prefix_segments, name = segment, *more_segments
        prefix = ""
        if prefix_segments:
            prefix = "/".join(prefix_segments) + "/"
        return cls(name, bucket=bucket, prefix=prefix, mode=mode)

    @classmethod
    def from_key(
        cls,
        key: str,
        *,
        bucket: str,
        mode: Mode = Mode.DOLOTO,
    ) -> t.Self:
        """Build from a full object key (no bucket, no scheme).

        >>> S3Ref.from_key("dumps/daily/part_00.parquet", bucket="my-bucket")
        s3://my-bucket/dumps/daily/part_00.parquet
        """
        return cls.from_segments(*key.split("/"), bucket=bucket, mode=mode)

    @classmethod
    def from_path(
        cls,
        path: str,
        *,
        mode: Mode = Mode.DOLOTO,
    ) -> t.Self:
        """Build from a bucket-qualified path (no scheme), as pyarrow fs wants it.

        >>> S3Ref.from_path("my-bucket/dumps/daily/part_00.parquet")
        s3://my-bucket/dumps/daily/part_00.parquet
        """
        bucket, _, key = path.partition("/")
        return cls.from_key(key, bucket=bucket, mode=mode)

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        mode: Mode = Mode.DOLOTO,
    ) -> t.Self:
        """Build from a full object url; a trailing slash is not an object.

        >>> S3Ref.from_url("s3://my-bucket/dumps/daily/part_00.parquet")
        s3://my-bucket/dumps/daily/part_00.parquet
        >>> S3Ref.from_url("s3://my-bucket/dumps/daily/")
        ValueError: invalid s3 object name: ''
        >>> S3Ref.from_url("my-bucket/dumps/daily/part_00.parquet")
        ValueError: not an s3 url: 'my-bucket/dumps/daily/part_00.parquet'
        """
        if not url.startswith(_URL_PREFIX):
            raise ValueError(f"not an s3 url: {url!r}")
        return cls.from_path(url[len(_URL_PREFIX) :], mode=mode)

    @classmethod
    def from_stub(
        cls,
        stub: str,
        *stubs: str,
        bucket: str,
        uid: uuid.UUID | str | None = None,
        mode: Mode = Mode.DOLOTO,
    ) -> t.Self:
        """Build a run-scoped root under `.doloto/`: stubs, then `<utc minute>__<uid>`.

        >>> S3Ref.from_stub("ingestion", "users", bucket="my-bucket", uid="run42")
        s3://my-bucket/.doloto/ingestion/users/2026-10-02T14-44__run42
        >>> S3Ref.from_stub("dumps", bucket="my-bucket", uid=uuid.UUID("502bb85f-..."))
        s3://my-bucket/.doloto/dumps/2026-10-02T14-44__502bb85fb9774134bd33bea17aeb911b
        >>> S3Ref.from_stub("dumps", bucket="my-bucket")
        s3://my-bucket/.doloto/dumps/2026-10-02T14-44__<uuid4 hex>
        """
        uid = uid or uuid.uuid4()
        if isinstance(uid, uuid.UUID):
            uid = uid.hex
        ts = dtm.datetime.now(dtm.UTC).strftime("%Y-%m-%dT%H-%M")
        return cls.from_segments(
            ".doloto",
            stub,
            *stubs,
            f"{ts}__{uid}",
            bucket=bucket,
            mode=mode,
        )

    @classmethod
    def preconfigure(
        cls,
        *,
        default_bucket: str,
        default_prefix: str = "",
        default_mode: Mode = Mode.DOLOTO,
    ) -> functools.partial[t.Self]:
        """Bind bucket/prefix/mode; the partial takes the object name.

        >>> make_ref = S3Ref.preconfigure(
        ...     default_bucket="my-bucket", default_prefix="dumps/"
        ... )
        >>> make_ref("part_00.parquet")
        s3://my-bucket/dumps/part_00.parquet
        """
        return functools.partial(
            cls,
            bucket=default_bucket,
            prefix=default_prefix,
            mode=default_mode,
        )

    # Neighbours

    def make_child(
        self,
        name: str,
        *,
        mode: Mode | None = None,
    ) -> t.Self:
        return self.__class__(
            name,
            bucket=self.bucket,
            prefix=self.slashed_key,
            mode=mode or self.mode,
        )

    def make_descendant(
        self,
        relative_key: str,
        *,
        mode: Mode | None = None,
    ) -> t.Self:
        prefix, sep, name = relative_key.rpartition("/")
        return self.__class__(
            name,
            bucket=self.bucket,
            prefix=f"{self.slashed_key}{prefix}{sep}",
            mode=mode or self.mode,
        )

    def make_neighbour(
        self,
        name: str,
        *,
        mode: Mode | None = None,
    ) -> t.Self:
        return self.__class__(
            name,
            bucket=self.bucket,
            prefix=self.prefix,
            mode=mode or self.mode,
        )

    @property
    def has_parent(self) -> bool:
        return bool(self.prefix)

    def is_under(self, ancestor: t.Self) -> bool:
        return self.bucket == ancestor.bucket and self.key.startswith(
            ancestor.slashed_key,
        )

    def relative_key(self, ancestor: t.Self) -> str:
        if not self.is_under(ancestor):
            raise ValueError(f"{self.path!r} is not under {ancestor.slashed_path!r}")
        return self.key[len(ancestor.slashed_key) :]

    def make_parent(self, *, mode: Mode | None = None) -> t.Self:
        if not self.has_parent:
            raise ValueError(f"s3 ref has no parent: {self.key!r}")
        prefix, sep, name = self.prefix[:-1].rpartition("/")
        return self.__class__(
            name,
            bucket=self.bucket,
            prefix=prefix + sep,
            mode=mode or self.mode,
        )


class FlexS3Ref(S3Ref):
    @staticmethod
    def __clean_slashes(value: str) -> str:
        return _MULTI_SLASH_RE.sub("/", value).strip("/")

    def __init__(
        self,
        name: str,
        *,
        bucket: str,
        prefix: str = "",
        mode: Mode = Mode.DOLOTO,
    ) -> None:
        if isinstance(name, str):
            name = self.__clean_slashes(name)
        if isinstance(prefix, str):
            prefix = self.__clean_slashes(prefix)
            if prefix:
                prefix = f"{prefix}/"
        super().__init__(name, bucket=bucket, prefix=prefix, mode=mode)


class S3ObjectProto(t.Protocol):
    @property
    def ref(self) -> S3Ref: ...

    @property
    def bytes(self) -> int: ...


def refify_url(url: str | S3Ref, *, strict: bool = False) -> S3Ref:
    """A string becomes a default ref; a ref passes through.

    >>> refify_url("s3://my-bucket/dumps/manifest")
    s3://my-bucket/dumps/manifest
    >>> refify_url("s3://my-bucket/dumps/daily/")
    s3://my-bucket/dumps/daily  (slashed_url "s3://my-bucket/dumps/daily/")
    >>> refify_url("s3://my-bucket/dumps/daily/", strict=True)
    ValueError: invalid s3 object name: ''
    """
    if isinstance(url, S3Ref):
        return url
    if not strict:
        url = url.rstrip("/")
    return S3Ref.from_url(url)


def refify_path(path: str | S3Ref, *, strict: bool = False) -> S3Ref:
    """A string becomes a default ref; a ref passes through.

    >>> refify_path("my-bucket/dumps/manifest")
    s3://my-bucket/dumps/manifest
    >>> refify_path("my-bucket/dumps/daily/")
    s3://my-bucket/dumps/daily
    """
    if isinstance(path, S3Ref):
        return path
    if not strict:
        path = path.rstrip("/")
    return S3Ref.from_path(path)
