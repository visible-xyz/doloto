import abc
import typing as t


class Immutable:
    def _set_attrs(self, **attrs: t.Any) -> None:
        for name, value in attrs.items():
            object.__setattr__(self, name, value)

    def __setattr__(self, name: str, value: t.Any) -> t.Never:
        raise AttributeError(f"{type(self).__name__} is immutable")

    def __delattr__(self, name: str) -> t.Never:
        raise AttributeError(f"{type(self).__name__} is immutable")


class PicklableImmutable(Immutable, abc.ABC):
    @abc.abstractmethod
    def _get_state(self) -> dict[str, t.Any]: ...

    def __getstate__(self) -> dict[str, t.Any]:
        return self._get_state()

    def __setstate__(self, state: dict[str, t.Any]) -> None:
        self._set_attrs(**state)
