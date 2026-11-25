"""In-memory ``DiscCodeReader`` for tests: answers a configured code per image path."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domain.disc_ids import DiscCode


class FakeDiscCodeReader:
    """Maps an image path to the :class:`DiscCode` it carries; other paths answer ``default``.

    ``calls`` records each ``(path, family)`` asked for; ``problem`` is what
    ``disc_code_problem`` answers for a path with no code.
    """

    def __init__(
        self,
        codes: dict[str, DiscCode] | None = None,
        *,
        default: DiscCode | None = None,
        problem: tuple[str, str] | None = ("no_disc_id", ""),
    ) -> None:
        self.codes: dict[str, DiscCode] = dict(codes or {})
        self.default = default
        self.problem = problem
        self.calls: list[tuple[str, str]] = []

    def read_disc_code(self, path: str, family: str) -> DiscCode | None:
        self.calls.append((path, family))
        return self.codes.get(path, self.default)

    def disc_code_problem(self, path: str, family: str) -> tuple[str, str] | None:
        return None if self.codes.get(path, self.default) is not None else self.problem
