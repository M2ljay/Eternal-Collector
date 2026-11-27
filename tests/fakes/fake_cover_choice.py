"""In-memory ``CoverChoiceReader`` for ArtworkService tests."""

from __future__ import annotations


class FakeCoverChoice:
    """``CoverChoiceReader`` that never chooses case art unless told to.

    ``case_paths`` maps a rom_id to the case image to choose for it;
    ``restyle`` lists the rom_ids whose tile shows the other style; every
    ``do_mark_published`` call is recorded in ``published``.
    """

    def __init__(self, case_paths: dict[int, str] | None = None, restyle: list[int] | None = None) -> None:
        self.case_paths: dict[int, str] = dict(case_paths or {})
        self.restyle: list[int] = list(restyle or [])
        self.published: list[int] = []

    def do_choose_cover_path(self, rom_id: int | str, plain_path: str) -> str:
        return self.case_paths.get(int(rom_id), plain_path)

    def do_has_case_cover(self, rom_id: int | str) -> bool:
        return int(rom_id) in self.case_paths

    def do_restyle_candidates(self, rom_ids: list[int]) -> list[int]:
        return [r for r in rom_ids if r in self.restyle]

    def do_mark_published(self, rom_id: int) -> None:
        self.published.append(rom_id)
