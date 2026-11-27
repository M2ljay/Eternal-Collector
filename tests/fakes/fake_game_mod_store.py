"""In-memory ``GameModStore`` for service tests: configured files, folders, listings and sources; records writes."""

from __future__ import annotations

from dataclasses import dataclass, field

from domain.game_mods import InstallOutcome, ModEntryInfo, PlannedWrite, SourceEntry


@dataclass
class FakeSource:
    """One Downloads entry: whether it is a folder, what it would install, and its change stamp."""

    is_dir: bool = False
    entries: list[SourceEntry] = field(default_factory=list)
    stamp: str = "stamp-1"
    read_error: Exception | None = None


class FakeGameModStore:
    """``GameModStore`` over dictionaries. Paths are compared as given (Windows spelling in these tests)."""

    def __init__(self, *, downloads: str = "C:\\Users\\me\\Downloads") -> None:
        self.downloads = downloads
        self.files: dict[str, str | None] = {}
        self.dirs: set[str] = {downloads}
        self.listings: dict[str, list[ModEntryInfo]] = {}
        self.sources: dict[str, FakeSource] = {}
        self.source_listing: list[ModEntryInfo] = []
        self.kinds: dict[str, str] = {}
        self.running: frozenset[str] | None = frozenset()
        self.install_outcome: InstallOutcome | None = None
        self.replace_result: bool | Exception = True
        self.move_error: Exception | None = None
        self.open_result = True
        self.installs: list[tuple[str, str, tuple[PlannedWrite, ...], frozenset[str], str]] = []
        self.moves: list[tuple[str, str, str]] = []
        self.replacements: list[tuple[str, str, str, str]] = []
        self.opened: list[str] = []
        self.file_names: dict[str, list[str]] = {}
        self.zips: dict[tuple[str, str], str] = {}
        self.created: list[tuple[str, str]] = []
        self.create_result = True
        self.binaries: dict[str, bytes] = {}
        self.found: dict[tuple[str, str], list[str]] = {}
        self.copies: list[tuple[str, str]] = []
        self.installer_result: tuple[int | None, str] = (0, "Installed CIA successfully.")
        self.installer_runs: list[tuple[str, tuple[str, ...]]] = []

    def downloads_folder(self) -> str:
        return self.downloads

    def is_file(self, path: str) -> bool:
        return path in self.files

    def is_dir(self, path: str) -> bool:
        return path in self.dirs

    def load_text(self, path: str) -> str | None:
        return self.files.get(path)

    def list_folder(self, folder: str, limit: int) -> tuple[list[ModEntryInfo], bool]:
        entries = self.listings.get(folder, [])
        return (entries[:limit], len(entries) > limit)

    def stat_names(self, folder: str, names: tuple[str, ...]) -> list[ModEntryInfo]:
        return [e for e in self.listings.get(folder, []) if e.name in names]

    def list_sources(self, folder: str, limit: int) -> tuple[list[ModEntryInfo], bool]:
        return (self.source_listing[:limit], len(self.source_listing) > limit)

    def list_file_names(self, folder: str, limit: int) -> list[str]:
        return self.file_names.get(folder, [])[:limit]

    def read_zip_text(self, zip_path: str, member: str) -> str | None:
        return self.zips.get((zip_path, member))

    def create_text(self, path: str, new_text: str) -> bool:
        if not self.create_result or path in self.files:
            return False
        self.created.append((path, new_text))
        return True

    def read_bytes(self, path: str, limit: int) -> bytes | None:
        data = self.binaries.get(path)
        return data[:limit] if data is not None else None

    def find_files(self, root: str, name: str, limit: int) -> list[str]:
        return self.found.get((root, name), [])[:limit]

    def copy_to_backup(self, path: str, backup: str) -> None:
        self.copies.append((path, backup))

    def run_installer(self, exe: str, args: tuple[str, ...], timeout: float) -> tuple[int | None, str]:
        self.installer_runs.append((exe, args))
        return self.installer_result

    def source_path(self, name: str) -> str | None:
        return f"{self.downloads}\\{name}" if name in self.sources else None

    def _source(self, path: str) -> FakeSource | None:
        return self.sources.get(path.rsplit("\\", 1)[-1])

    def source_stamp(self, path: str) -> str | None:
        source = self._source(path)
        return source.stamp if source else None

    def read_source_entries(self, path: str) -> list[SourceEntry]:
        source = self._source(path)
        if source is None:
            raise OSError("gone")
        if source.read_error is not None:
            raise source.read_error
        return list(source.entries)

    def probe_kinds(self, root: str, rel_paths: tuple[str, ...]) -> dict[str, str]:
        return {rel: self.kinds.get(rel, "missing") for rel in rel_paths}

    def install(
        self, source: str, root: str, writes: tuple[PlannedWrite, ...], replaces: frozenset[str], backup: str
    ) -> InstallOutcome:
        self.installs.append((source, root, writes, replaces, backup))
        return self.install_outcome or InstallOutcome(len(writes), len(replaces))

    def move_to_backup(self, root: str, name: str, backup: str) -> None:
        if self.move_error is not None:
            raise self.move_error
        self.moves.append((root, name, backup))

    def replace_text(self, path: str, expected: str, new_text: str, backup: str) -> bool:
        if isinstance(self.replace_result, Exception):
            raise self.replace_result
        self.replacements.append((path, expected, new_text, backup))
        return self.replace_result

    def open_folder(self, path: str) -> bool:
        self.opened.append(path)
        return self.open_result

    def running_executable_names(self) -> frozenset[str] | None:
        return self.running
