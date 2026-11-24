"""In-memory ``PluginReleaseSource`` for plugin self-update tests."""

from __future__ import annotations

import hashlib

from lib.errors import PluginReleaseFetchError


class FakePluginReleaseSource:
    """Serves a fixed ``update.json`` body and artifact bytes; records every URL asked for.

    ``manifest_error`` / ``download_error`` make the next matching call raise
    ``PluginReleaseFetchError``.
    """

    def __init__(self, manifest: bytes = b"{}", artifact: bytes = b"") -> None:
        self.manifest = manifest
        self.artifact = artifact
        self.manifest_error: str | None = None
        self.download_error: str | None = None
        self.manifest_urls: list[str] = []
        self.download_urls: list[str] = []

    def fetch_manifest(self, url: str, max_bytes: int) -> bytes:
        self.manifest_urls.append(url)
        if self.manifest_error is not None:
            raise PluginReleaseFetchError(self.manifest_error)
        return self.manifest[: max_bytes + 1]

    def download(self, url: str, dest_path: str, max_bytes: int) -> tuple[int, str]:
        self.download_urls.append(url)
        if self.download_error is not None:
            raise PluginReleaseFetchError(self.download_error)
        body = self.artifact[: max_bytes + 1]
        with open(dest_path, "wb") as f:
            f.write(body)
        return len(body), hashlib.sha256(body).hexdigest()
