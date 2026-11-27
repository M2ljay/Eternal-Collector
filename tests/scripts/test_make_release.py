"""``scripts/make_release.sh`` ships an install manifest that matches the zip it is in."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import zipfile

import pytest

from adapters.install_files import InstallFileAdapter
from services.install_integrity import InstallIntegrityService, InstallIntegrityServiceConfig

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(ROOT, "scripts", "make_release.sh")


@pytest.fixture(scope="module")
def release(tmp_path_factory):
    if shutil.which("bash") is None or not os.path.isfile(os.path.join(ROOT, "dist", "index.js")):
        pytest.skip("needs bash and a built dist/index.js")
    with open(os.path.join(ROOT, "package.json"), encoding="utf-8") as f:
        version = json.load(f)["version"]
    out = tmp_path_factory.mktemp("release")
    subprocess.run(["bash", SCRIPT, str(out)], env={**os.environ, "SKIP_BUILD": "1"}, check=True, capture_output=True)
    zip_path = out / f"romm-dock-{version}.zip"
    extracted = tmp_path_factory.mktemp("installed")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extracted)
        names = zf.namelist()
    return version, extracted / "romm-dock", names


def _check(folder):
    async def run():
        svc = InstallIntegrityService(
            config=InstallIntegrityServiceConfig(
                loop=asyncio.get_running_loop(),
                logger=logging.getLogger("t"),
                scanner=InstallFileAdapter(str(folder)),
                current_version="",
            )
        )
        return await svc.get_report()

    # Not asyncio.run(): it clears the thread's current event loop, which later
    # tests that call asyncio.get_event_loop() rely on.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(run())
    finally:
        loop.close()


def test_manifest_lists_every_other_file(release):
    version, folder, names = release
    manifest = json.loads((folder / "install-manifest.json").read_text())
    assert manifest["format"] == 1
    assert manifest["version"] == version
    listed = {f"romm-dock/{f['path']}" for f in manifest["files"]}
    assert listed == set(names) - {"romm-dock/install-manifest.json"}


def test_a_fresh_extract_is_ok(release):
    _, folder, _ = release
    assert _check(folder)["status"] == "ok"


def test_an_interrupted_extract_is_incomplete(release, tmp_path):
    _, folder, _ = release
    copy = tmp_path / "romm-dock"
    shutil.copytree(folder, copy)
    shutil.rmtree(copy / "py_modules" / "services")
    report = _check(copy)
    assert report["status"] == "incomplete"
    assert "py_modules/services/game_mods/service.py" in report["missing"]


def test_entries_are_in_install_order(release):
    """Decky's extractall stops at the first file it cannot write, so the lock-prone files go last."""
    _, _, names = release
    rel = [n.removeprefix("romm-dock/") for n in names]

    def group(name):
        if name == "install-manifest.json":
            return 0
        if name.startswith("py_modules/native/"):
            return 5
        if name.startswith("bin/"):
            return 4
        if name.startswith("py_modules/"):
            return 1
        return 2 if name == "main.py" else 3

    assert rel[0] == "install-manifest.json"
    assert [group(n) for n in rel] == sorted(group(n) for n in rel)
    assert rel[-1].startswith("py_modules/native/")
    assert rel.index("main.py") > rel.index("py_modules/services/achievement_journal.py")
    assert rel.index("main.py") < rel.index("bin/rom-launcher.exe")
    assert rel.index("bin/rom-launcher.exe") < rel.index("py_modules/native/gavel-x86_64-windows.dll")
    assert rel == sorted(rel, key=lambda n: (group(n), n))


def test_install_order_is_reproducible(release, tmp_path):
    version, _, names = release
    subprocess.run(
        ["bash", SCRIPT, str(tmp_path)], env={**os.environ, "SKIP_BUILD": "1"}, check=True, capture_output=True
    )
    with zipfile.ZipFile(tmp_path / f"romm-dock-{version}.zip") as zf:
        assert zf.namelist() == names
