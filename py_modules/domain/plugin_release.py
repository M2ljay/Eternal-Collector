"""The fork's release channel — what a published build is and whether it is newer.

Pure: the version scheme, the release-branch layout the channel is read from, and
the validation an ``update.json`` must pass before anything it names is fetched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

RELEASE_REPO = "M2ljay/Eternal-Collector"
RELEASE_BRANCH = "release"
RELEASE_BASE_URL = f"https://raw.githubusercontent.com/{RELEASE_REPO}/{RELEASE_BRANCH}/"
MANIFEST_URL = RELEASE_BASE_URL + "update.json"
ARTIFACT_NAME = "romm-dock.zip"
ARTIFACT_URL = RELEASE_BASE_URL + ARTIFACT_NAME

# The same repository under its name before the GitHub rename; raw.githubusercontent.com
# still serves it. Builds up to 0.33.0-win.17 accept only this artifact URL in
# update.json, so the channel publishes it until none of those builds remain.
LEGACY_RELEASE_REPO = "M2ljay/Eternal-Romm"
LEGACY_ARTIFACT_URL = f"https://raw.githubusercontent.com/{LEGACY_RELEASE_REPO}/{RELEASE_BRANCH}/{ARTIFACT_NAME}"
ACCEPTED_ARTIFACT_URLS = (ARTIFACT_URL, LEGACY_ARTIFACT_URL)
PUBLISHED_ARTIFACT_URL = LEGACY_ARTIFACT_URL

CHECK_INTERVAL_SECONDS = 6 * 60 * 60
MAX_MANIFEST_BYTES = 64 * 1024
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_NOTES_CHARS = 2000

_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-win\.(\d+))?$")
_FORK_VERSION_RE = re.compile(r"^v?\d+\.\d+\.\d+-win\.\d+$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ManifestError(ValueError):
    """An ``update.json`` that cannot be acted on; the message says why."""


@dataclass(frozen=True)
class ReleaseManifest:
    """One published build, as its ``update.json`` describes it."""

    version: str
    sha256: str
    size: int
    notes: str
    url: str


def parse_version(text: object) -> tuple[int, int, int, int] | None:
    """``"0.33.0-win.17"`` -> ``(0, 33, 0, 17)``; a plain ``"0.33.0"`` has build 0.

    Every other shape (another pre-release tag, a fourth dot part, garbage) is
    ``None``: a version that cannot be read is never something to install.
    """
    if not isinstance(text, str):
        return None
    match = _VERSION_RE.match(text.strip())
    if match is None:
        return None
    major, minor, patch, build = match.groups()
    return int(major), int(minor), int(patch), int(build or 0)


def is_fork_build(version: str) -> bool:
    """True for a version carrying this fork's ``-win.N`` build counter."""
    return bool(_FORK_VERSION_RE.match(version.strip()))


def is_newer(current: str, candidate: str) -> bool:
    """Strictly newer by number, never by string order (``win.10`` > ``win.9``).

    Equal, older, or either side unreadable is ``False``.
    """
    have = parse_version(current)
    want = parse_version(candidate)
    if have is None or want is None:
        return False
    return want > have


def parse_manifest(payload: object) -> ReleaseManifest:
    """Validate a decoded ``update.json`` and return the build it describes.

    Raises :class:`ManifestError` when any field is missing or wrong. The
    artifact URL must be exactly the channel's own zip, under the repository's
    current or legacy name (:data:`ACCEPTED_ARTIFACT_URLS`): the installer runs
    whatever it is handed, so nothing else is accepted.
    """
    if not isinstance(payload, dict):
        raise ManifestError("update.json is not a JSON object")
    version = payload.get("version")
    if not isinstance(version, str) or parse_version(version) is None:
        raise ManifestError(f"update.json has an unreadable version: {version!r}")
    sha256 = payload.get("sha256")
    if not isinstance(sha256, str) or not _SHA256_RE.match(sha256):
        raise ManifestError("update.json has no valid sha256")
    size = payload.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_ARTIFACT_BYTES:
        raise ManifestError(f"update.json has an invalid size: {size!r}")
    url = payload.get("url")
    if not isinstance(url, str) or url not in ACCEPTED_ARTIFACT_URLS:
        raise ManifestError(f"update.json points somewhere other than {ARTIFACT_URL}")
    notes = payload.get("notes", "")
    if not isinstance(notes, str):
        notes = ""
    return ReleaseManifest(
        version=version.strip(),
        sha256=sha256,
        size=size,
        notes=notes.strip()[:MAX_NOTES_CHARS],
        url=url,
    )
