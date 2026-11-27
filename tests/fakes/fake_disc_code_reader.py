"""In-memory ``DiscCodeReader`` for tests: answers a configured code per image path."""

from __future__ import annotations

from typing import TYPE_CHECKING

from domain.console_ids import TitleIdAnswer
from domain.disc_ids import Ps2ElfCrc

if TYPE_CHECKING:
    from domain.disc_ids import DiscCode


class FakeDiscCodeReader:
    """Maps an image path to the :class:`DiscCode` it carries (and a PS2 boot ELF CRC); others answer ``default``.

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
        self.elf_crcs: dict[str, Ps2ElfCrc] = {}
        self.iso_members: dict[tuple[str, tuple[str, ...]], bytes] = {}
        self.xbox_titles: dict[str, TitleIdAnswer] = {}

    def read_disc_code(self, path: str, family: str) -> DiscCode | None:
        self.calls.append((path, family))
        return self.codes.get(path, self.default)

    def disc_code_problem(self, path: str, family: str) -> tuple[str, str] | None:
        return None if self.codes.get(path, self.default) is not None else self.problem

    def read_ps2_elf_crc(self, path: str) -> Ps2ElfCrc:
        return self.elf_crcs.get(path, Ps2ElfCrc(None, "the boot executable SYSTEM.CNF names is missing or not an ELF"))

    def read_iso_member(self, path: str, parts: tuple[str, ...], limit: int) -> bytes | None:
        data = self.iso_members.get((path, parts))
        return data[:limit] if data is not None else None

    def read_xbox360_title_id(self, path: str) -> TitleIdAnswer:
        return self.xbox_titles.get(path, TitleIdAnswer(None, "the image is not an Xbox 360 (XDVDFS) disc"))
