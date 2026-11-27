"""In-memory ``NowPlayingStore`` for service tests."""

from __future__ import annotations

import copy


class FakeNowPlayingStore:
    """Holds the document in memory; ``fail_writes`` makes every write raise ``OSError``."""

    def __init__(self, document: object | None = None) -> None:
        self.document = copy.deepcopy(document)
        self.fail_writes = False
        self.writes = 0
        self.removes = 0

    def read(self) -> object | None:
        return copy.deepcopy(self.document)

    def write(self, document: dict[str, object]) -> None:
        if self.fail_writes:
            raise OSError("disk full")
        self.writes += 1
        self.document = copy.deepcopy(document)

    def remove(self) -> None:
        if self.fail_writes:
            raise OSError("disk full")
        self.removes += 1
        self.document = None
