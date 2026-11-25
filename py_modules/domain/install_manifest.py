"""The install manifest and what an installed plugin folder is checked against.

A release zip carries ``install-manifest.json`` at its top: the path, size and
SHA-256 of every other file in the zip. Decky Loader v3.3.1's installer can
leave a half-copied folder behind — it carries on past a failed delete of the
old folder and aborts mid-extract on a locked file, see
``docs/architecture/plugin-self-update.md`` — so the plugin compares its own
folder with the manifest at start and reports what does not match.

This module owns the manifest's format, the comparison and the verdict. Which
files exist and what they hash to are read elsewhere; everything here is pure
and imports the standard library only, because it must load when other plugin
modules cannot.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

MANIFEST_NAME = "install-manifest.json"
MANIFEST_FORMAT = 1

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

OK = "ok"
INCOMPLETE = "incomplete"
STALE_FILES = "stale_files"
UNCHECKED = "unchecked"
"""Verdicts: every file matches; a file is missing or differs; only leftover
``.py`` files from an older build; no manifest to check against (a dev install)."""


class InstallManifestError(ValueError):
    """The manifest file is present but cannot be used."""


@dataclass(frozen=True)
class ManifestEntry:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class InstallManifest:
    version: str
    entries: tuple[ManifestEntry, ...]

    def paths(self) -> frozenset[str]:
        return frozenset(e.path for e in self.entries)


@dataclass(frozen=True)
class IntegrityReport:
    """What the installed folder looked like against its manifest.

    ``missing`` and ``mismatched`` (size or hash) make the install incomplete;
    ``extra`` lists ``.py`` files under ``py_modules/`` the manifest does not
    name — leftovers of an older build — and ``shadowing`` those of them that
    sit beside a package of the same name (``services/downloads.py`` next to
    ``services/downloads/``). ``hashes_checked`` is False until the slower hash
    pass has run.
    """

    status: str
    expected_version: str | None
    missing: tuple[str, ...] = ()
    mismatched: tuple[str, ...] = ()
    extra: tuple[str, ...] = ()
    shadowing: tuple[str, ...] = ()
    hashes_checked: bool = False
    detail: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "expected_version": self.expected_version,
            "missing": list(self.missing),
            "mismatched": list(self.mismatched),
            "extra": list(self.extra),
            "shadowing": list(self.shadowing),
            "hashes_checked": self.hashes_checked,
            "detail": self.detail,
        }


def parse_manifest(raw: bytes) -> InstallManifest:
    """Parse ``install-manifest.json``; raise :class:`InstallManifestError` when it is unusable."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise InstallManifestError(f"{MANIFEST_NAME} is not valid JSON: {e}") from e
    if not isinstance(data, dict) or data.get("format") != MANIFEST_FORMAT:
        raise InstallManifestError(f"{MANIFEST_NAME} has an unknown format")
    version = data.get("version")
    files = data.get("files")
    if not isinstance(version, str) or not version or not isinstance(files, list):
        raise InstallManifestError(f"{MANIFEST_NAME} is missing its version or file list")
    entries: list[ManifestEntry] = []
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            raise InstallManifestError(f"{MANIFEST_NAME} has a malformed entry")
        path, size, sha256 = item.get("path"), item.get("size"), item.get("sha256")
        if not (isinstance(path, str) and is_safe_relative(path)):
            raise InstallManifestError(f"{MANIFEST_NAME} names an unsafe path: {path!r}")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise InstallManifestError(f"{MANIFEST_NAME} has a bad size for {path}")
        if not isinstance(sha256, str) or not _SHA256_RE.match(sha256):
            raise InstallManifestError(f"{MANIFEST_NAME} has a bad hash for {path}")
        if path in seen:
            raise InstallManifestError(f"{MANIFEST_NAME} lists {path} twice")
        seen.add(path)
        entries.append(ManifestEntry(path, size, sha256))
    return InstallManifest(version, tuple(entries))


def is_safe_relative(path: str) -> bool:
    """A forward-slash relative path with no empty, ``.`` or ``..`` part and no drive."""
    if not path or path.startswith("/") or "\\" in path or ":" in path:
        return False
    return all(part not in ("", ".", "..") for part in path.split("/"))


def compare_sizes(
    manifest: InstallManifest,
    sizes: dict[str, int | None],
    present_py: frozenset[str],
    present_dirs: frozenset[str],
) -> IntegrityReport:
    """The verdict from file sizes alone.

    *sizes* maps every manifest path to its size on disk (``None`` when it is
    absent). *present_py* is every ``.py`` file found under ``py_modules/``
    and *present_dirs* every folder there, both as manifest-style paths.
    """
    missing = tuple(sorted(e.path for e in manifest.entries if sizes.get(e.path) is None))
    mismatched = tuple(
        sorted(e.path for e in manifest.entries if sizes.get(e.path) is not None and sizes[e.path] != e.size)
    )
    extra = tuple(sorted(present_py - manifest.paths()))
    shadowing = tuple(p for p in extra if p[: -len(".py")] in present_dirs)
    return IntegrityReport(
        status=_status(missing, mismatched, extra),
        expected_version=manifest.version,
        missing=missing,
        mismatched=mismatched,
        extra=extra,
        shadowing=shadowing,
    )


def with_hashes(report: IntegrityReport, manifest: InstallManifest, digests: dict[str, str | None]) -> IntegrityReport:
    """Fold the hash pass into a size verdict.

    *digests* maps the paths that were hashed (every path whose size matched)
    to their SHA-256, ``None`` when the file could not be read.
    """
    expected = {e.path: e.sha256 for e in manifest.entries}
    bad = {p for p, digest in digests.items() if digest != expected.get(p)}
    mismatched = tuple(sorted(set(report.mismatched) | bad))
    return IntegrityReport(
        status=_status(report.missing, mismatched, report.extra),
        expected_version=report.expected_version,
        missing=report.missing,
        mismatched=mismatched,
        extra=report.extra,
        shadowing=report.shadowing,
        hashes_checked=True,
    )


def unchecked(detail: str) -> IntegrityReport:
    return IntegrityReport(status=UNCHECKED, expected_version=None, hashes_checked=True, detail=detail)


def unreadable_manifest(detail: str) -> IntegrityReport:
    """A manifest that is present but unusable is itself a sign of a broken copy."""
    return IntegrityReport(status=INCOMPLETE, expected_version=None, hashes_checked=True, detail=detail)


def _status(missing: tuple[str, ...], mismatched: tuple[str, ...], extra: tuple[str, ...]) -> str:
    if missing or mismatched:
        return INCOMPLETE
    if extra:
        return STALE_FILES
    return OK
