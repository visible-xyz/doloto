import datetime as dtm
import time
import types
import typing as t


# NOTE: to consider: rounding datetimes to a timedelta step (floor / ceil / round);
#   prior art: `dtround` on PyPI (stdlib types, `base` anchor; looks unmaintained)


# ---- utcnow ---- #


def utcnow() -> dtm.datetime:
    return dtm.datetime.now(dtm.UTC)


def utcnow_fmt(fmt: str) -> str:
    return utcnow().strftime(fmt)


def utcnow_iso(*, sep: str = "T", timespec: str = "auto") -> str:
    return utcnow().isoformat(sep=sep, timespec=timespec)


# ---- elapsed ---- #


def elapsed_dt(start: dtm.datetime, now: dtm.datetime | None = None) -> dtm.timedelta:
    if now is None:
        now = utcnow()
    return now - start


def elapsed_dt_sec(start: dtm.datetime, now: dtm.datetime | None = None) -> float:
    return elapsed_dt(start, now).total_seconds()


def elapsed_epoch_sec(start: float, now: float | None = None) -> float:
    if now is None:
        now = time.time()
    return now - start


def elapsed_epoch(start: float, now: float | None = None) -> dtm.timedelta:
    return dtm.timedelta(seconds=elapsed_epoch_sec(start, now))


def elapsed_mono_sec(start: float, now: float | None = None) -> float:
    if now is None:
        now = time.monotonic()
    return now - start


def elapsed_mono(start: float, now: float | None = None) -> dtm.timedelta:
    return dtm.timedelta(seconds=elapsed_mono_sec(start, now))


# ---- timers ---- #


class MonoTimer:
    __slots__ = ("_checkpoints", "_last_stamp", "end", "start")

    def __init__(self) -> None:
        self.start = time.monotonic()
        self.end: float | None = None
        self._checkpoints: dict[str, float] = {}
        self._last_stamp = self.start

    @property
    def checkpoints(self) -> dict[str, float]:
        return self._checkpoints.copy()

    def __enter__(self) -> t.Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        self.finish()

    def checkpoint(self, name: str | None = None) -> float:
        if self.end is not None:
            raise RuntimeError("Timer has already been finished")
        stamp = time.monotonic()
        delta, self._last_stamp = stamp - self._last_stamp, stamp
        if name is not None:
            self._checkpoints[name] = delta
        return delta

    def finish(self) -> float:
        if self.end is not None:
            raise RuntimeError("Timer has already been finished")
        self.end = time.monotonic()
        return self.elapsed()

    def elapsed(self) -> float:
        if self.end is None:
            return time.monotonic() - self.start
        return self.end - self.start
