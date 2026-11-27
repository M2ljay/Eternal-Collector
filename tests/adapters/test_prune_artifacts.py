import os
from pathlib import Path

from adapters.prune_artifacts import PruneArtifactAdapter


def test_discovers_and_removes_only_named_rom_cache_files(tmp_path):
    covers = tmp_path / "covers"
    artwork = tmp_path / "artwork"
    covers.mkdir()
    artwork.mkdir()
    expected = [covers / "7.png", covers / "7.cover-meta.json", artwork / "7_grid.png"]
    for path in expected:
        path.write_bytes(b"x")
    unrelated = artwork / "8_grid.png"
    unrelated.write_bytes(b"keep")
    adapter = PruneArtifactAdapter(runtime_dir=str(tmp_path))

    artifacts = adapter.recovery_artifacts([7])
    sources = {Path(item["source_path"]) for item in artifacts}
    assert set(expected) <= sources
    assert artwork / "7_icon.png" in sources
    assert adapter.remove([7])["success"] is True
    assert all(not path.exists() for path in expected)
    assert unrelated.exists()


def test_removes_the_roms_case_art_with_its_other_cache_files(tmp_path):
    artwork = tmp_path / "artwork"
    artwork.mkdir()
    (tmp_path / "covers").mkdir()
    case_files = [artwork / "7_case.png", artwork / "7_case.json", artwork / "7_case_source.img"]
    for path in case_files:
        path.write_bytes(b"x")
    keep = artwork / "8_case.png"
    keep.write_bytes(b"keep")
    adapter = PruneArtifactAdapter(runtime_dir=str(tmp_path))

    sources = {Path(item["source_path"]) for item in adapter.recovery_artifacts([7])}
    assert set(case_files) <= sources
    assert adapter.remove([7])["success"] is True
    assert all(not path.exists() for path in case_files)
    assert keep.exists()


def test_unsealed_cleanup_does_not_follow_symlinked_cache_directory(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "7.png"
    target.write_bytes(b"keep")
    (tmp_path / "covers").symlink_to(outside, target_is_directory=True)
    (tmp_path / "artwork").mkdir()
    adapter = PruneArtifactAdapter(runtime_dir=str(tmp_path))

    result = adapter.remove([7])

    assert result["success"] is False
    assert target.read_bytes() == b"keep"


def test_preopened_cache_writer_prevents_artifact_deletion(tmp_path):
    covers = tmp_path / "covers"
    artwork = tmp_path / "artwork"
    covers.mkdir()
    artwork.mkdir()
    target = covers / "7.png"
    target.write_bytes(b"cached")
    adapter = PruneArtifactAdapter(runtime_dir=str(tmp_path))
    writer = os.open(target, os.O_WRONLY)
    try:
        result = adapter.remove([7])
    finally:
        os.close(writer)

    assert result["success"] is False
    assert "active writer" in result["message"]
    assert target.read_bytes() == b"cached"
