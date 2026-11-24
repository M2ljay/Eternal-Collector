"""Tests for RomInfoService — per-ROM save path resolution and local save discovery."""

import zipfile

from fakes.fake_active_core_resolver import FakeActiveCoreResolver
from fakes.fake_disc_code_reader import FakeDiscCodeReader
from fakes.fake_retrodeck_paths import FakeRetroDeckPaths

from domain.shortcut_data import EmulatorInvocation
from tests.services.saves._helpers import (
    STANDALONE_COMMANDS,
    _create_save,
    _install_rom,
    _seed_install,
    _set_sort_settings,
    _set_sort_settings_previous,
    make_service,
    make_standalone_service,
)


class TestFindSaveFiles:
    """Tests for find_save_files."""

    def test_finds_srm(self, tmp_path):
        svc, _ = make_service(tmp_path)
        _install_rom(svc, tmp_path)
        _create_save(tmp_path, system="gba", rom_name="pokemon")

        result = svc._rom_info.find_save_files(42)

        assert len(result) == 1
        assert result[0]["filename"] == "pokemon.srm"
        assert result[0]["path"].endswith("pokemon.srm")

    def test_finds_rtc_companion(self, tmp_path):
        svc, _ = make_service(tmp_path)
        _install_rom(svc, tmp_path, file_name="emerald.gba")
        _create_save(tmp_path, system="gba", rom_name="emerald", ext=".srm")
        _create_save(tmp_path, system="gba", rom_name="emerald", ext=".rtc", content=b"\x02" * 16)

        result = svc._rom_info.find_save_files(42)

        filenames = sorted(f["filename"] for f in result)
        assert filenames == ["emerald.rtc", "emerald.srm"]

    def test_multi_disc_uses_m3u_name(self, tmp_path):
        svc, _ = make_service(tmp_path)
        _seed_install(
            svc,
            55,
            file_path=str(tmp_path / "retrodeck" / "roms" / "psx" / "FF7" / "Final Fantasy VII.m3u"),
            system="psx",
            platform_slug="psx",
            rom_dir=str(tmp_path / "retrodeck" / "roms" / "psx" / "FF7"),
        )
        # With sort_by_content=True, saves land in saves_base/{content_dir} where
        # content_dir = last folder component of the ROM's directory = "FF7"
        saves_dir = tmp_path / "saves" / "FF7"
        saves_dir.mkdir(parents=True, exist_ok=True)
        (saves_dir / "Final Fantasy VII.srm").write_bytes(b"\x00" * 1024)

        result = svc._rom_info.find_save_files(55)

        assert any(f["filename"] == "Final Fantasy VII.srm" for f in result)

    def test_no_save_file_returns_empty(self, tmp_path):
        svc, _ = make_service(tmp_path)
        _install_rom(svc, tmp_path, rom_id=10, system="n64", file_name="zelda.z64")
        (tmp_path / "saves" / "n64").mkdir(parents=True, exist_ok=True)

        result = svc._rom_info.find_save_files(10)

        assert result == []

    def test_saves_dir_not_exists_returns_empty(self, tmp_path):
        svc, _ = make_service(tmp_path)
        _install_rom(svc, tmp_path)

        result = svc._rom_info.find_save_files(42)

        assert result == []

    def test_rom_not_installed_returns_empty(self, tmp_path):
        svc, _ = make_service(tmp_path)

        result = svc._rom_info.find_save_files(999)

        assert result == []

    def test_probes_system_extensions_when_slug_differs_from_system(self, tmp_path):
        """find_save_files keys save extensions by the normalized system, not the raw RomM slug (#899).

        Regression for the call-site leak: ``get_save_extensions`` was called
        with the raw RomM ``platform_slug`` (``sega-saturn``), which has no
        override and falls back to defaults — so a Saturn backup-RAM ``.bkr``
        save was never probed. The fix keys the lookup by the normalized
        ``system`` (``saturn``), whose override includes ``.bkr``. Reverting the
        rom_info.py change (passing ``platform_slug`` again) makes this fail:
        ``sega-saturn`` is not in ``_PLATFORM_OVERRIDES`` so ``.bkr`` is not in
        the probed extension list and the save is missed.
        """
        svc, _ = make_service(tmp_path)
        _seed_install(
            svc,
            70,
            file_path=str(tmp_path / "retrodeck" / "roms" / "saturn" / "Panzer Dragoon.cue"),
            system="saturn",
            platform_slug="sega-saturn",
        )
        # sort_by_content=True (RetroDECK default, no sort settings seeded) →
        # saves land in saves_base/{content_dir}, content_dir = "saturn".
        saves_dir = tmp_path / "saves" / "saturn"
        saves_dir.mkdir(parents=True, exist_ok=True)
        (saves_dir / "Panzer Dragoon.bkr").write_bytes(b"\x00" * 256)

        result = svc._rom_info.find_save_files(70)

        assert [f["filename"] for f in result] == ["Panzer Dragoon.bkr"]


class TestGetRomSaveInfo:
    """Tests for get_rom_save_info."""

    def test_returns_info_for_installed_rom(self, tmp_path):
        svc, _ = make_service(tmp_path)
        _install_rom(svc, tmp_path)

        result = svc._rom_info.get_rom_save_info(42)

        assert result is not None
        assert result["system"] == "gba"
        assert result["rom_name"] == "pokemon"
        assert result["saves_dir"].endswith("saves/gba")

    def test_returns_none_for_missing_rom(self, tmp_path):
        svc, _ = make_service(tmp_path)

        result = svc._rom_info.get_rom_save_info(999)

        assert result is None

    def test_returns_none_for_empty_system(self, tmp_path):
        svc, _ = make_service(tmp_path)
        _seed_install(svc, 42, file_path="/some/path.gba", system="", platform_slug="")

        result = svc._rom_info.get_rom_save_info(42)

        assert result is None

    # ------------------------------------------------------------------
    # Regression tests for issue #238 — Rule 1: when a save-sort migration
    # is pending, prefer save_sort_settings_previous so sync reads the
    # layout RetroArch actually wrote to during the session that just
    # ended.
    # ------------------------------------------------------------------

    def test_get_rom_save_info_prefers_previous_sort_settings_when_migration_pending(self, tmp_path):
        """Pending migration: previous (OLD) sort settings override current (NEW) (#238)."""
        svc, _ = make_service(
            tmp_path,
            active_core=FakeActiveCoreResolver(default=("mgba_libretro", "mGBA")),
            get_core_name=lambda core_so: "mGBA",
        )
        _install_rom(svc, tmp_path)
        # NEW layout (what settings currently say):
        _set_sort_settings(svc, {"sort_by_content": True, "sort_by_core": True})
        # OLD layout (what the session actually wrote to):
        _set_sort_settings_previous(svc, {"sort_by_content": True, "sort_by_core": False})

        result = svc._rom_info.get_rom_save_info(42)

        assert result is not None
        # OLD layout: no /mGBA subdir.
        assert result["saves_dir"].endswith("saves/gba")
        assert "/mGBA" not in result["saves_dir"]

    def test_get_rom_save_info_uses_current_sort_settings_when_no_pending_migration(self, tmp_path):
        """No pending migration: use current sort settings (#238)."""
        svc, _ = make_service(
            tmp_path,
            active_core=FakeActiveCoreResolver(default=("mgba_libretro", "mGBA")),
            get_core_name=lambda core_so: "mGBA",
        )
        _install_rom(svc, tmp_path)
        # Only save_sort_settings is present — no pending migration marker at all.
        _set_sort_settings(svc, {"sort_by_content": True, "sort_by_core": True})
        assert svc._rom_info.pending_sort_settings() is None

        result = svc._rom_info.get_rom_save_info(42)

        assert result is not None
        # CURRENT layout: /mGBA subdir is appended because sort_by_core=True.
        assert result["saves_dir"].endswith("saves/gba/mGBA")

    def test_pending_sort_settings_rejects_empty_dict_half_state(self, tmp_path):
        """Empty-dict ``save_sort_settings_previous`` must NOT count as pending (#238 review).

        Freezes the contract: ``get_rom_save_info`` and ``is_save_sort_changed``
        must agree on what counts as pending. Before ``pending_sort_settings``
        was introduced, a literal empty dict at ``save_sort_settings_previous``
        would put the service in a half-state — ``get_rom_save_info`` would
        fall back to current settings (``{} or current``), but
        ``is_save_sort_changed`` would treat the same ``{}`` as pending
        (``is not None``). This test locks in the agreement.
        """
        svc, _ = make_service(
            tmp_path,
            active_core=FakeActiveCoreResolver(default=("mgba_libretro", "mGBA")),
            get_core_name=lambda core_so: "mGBA",
        )
        _install_rom(svc, tmp_path)
        # Half-state input: empty previous, populated current (NEW).
        _set_sort_settings_previous(svc, {})
        _set_sort_settings(svc, {"sort_by_content": True, "sort_by_core": True})

        # Both call sites must agree there is NO pending migration.
        assert svc._rom_info.is_save_sort_changed() is False
        assert svc._rom_info.pending_sort_settings() is None

        result = svc._rom_info.get_rom_save_info(42)
        assert result is not None
        # Reads CURRENT settings (NEW layout), not the empty previous —
        # mGBA subdir is appended because sort_by_core=True.
        assert result["saves_dir"].endswith("saves/gba/mGBA")

    # ------------------------------------------------------------------
    # Regression tests for issue #232 — RomInfoService must resolve the
    # RetroArch ``corename`` via the .info parser when sort_by_core is
    # active, and must fall back with a warning when it cannot.
    # ------------------------------------------------------------------

    def test_default_sort_only_by_content_no_core_subdir(self, tmp_path):
        """sort_by_core=False (RetroDECK default) → no core subdir."""
        svc, _ = make_service(
            tmp_path,
            active_core=FakeActiveCoreResolver(default=("mgba_libretro", "mGBA")),
            get_core_name=lambda core_so: "mGBA",
        )
        _install_rom(svc, tmp_path)
        _set_sort_settings(svc, {"sort_by_content": True, "sort_by_core": False})

        result = svc._rom_info.get_rom_save_info(42)

        assert result is not None
        assert result["saves_dir"].endswith("saves/gba")
        assert "/mGBA" not in result["saves_dir"]

    def test_sort_by_core_appends_retroarch_corename(self, tmp_path):
        """sort_by_core=True with resolvable corename → saves_dir ends in /{system}/{corename}."""
        svc, _ = make_service(
            tmp_path,
            active_core=FakeActiveCoreResolver(default=("mgba_libretro", "mGBA")),
            get_core_name=lambda core_so: "mGBA",
        )
        _install_rom(svc, tmp_path)
        _set_sort_settings(svc, {"sort_by_content": True, "sort_by_core": True})

        result = svc._rom_info.get_rom_save_info(42)

        assert result is not None
        assert result["saves_dir"].endswith("saves/gba/mGBA")

    def test_save_dir_differs_by_per_game_override(self, tmp_path):
        """RESULT-FLIP: two gba ROMs, one pinned to gpSP + one default, get different save dirs.

        With sort_by_core active, the per-core save subdir is named after the
        resolved core's ``.info`` corename. The override ROM resolves to gpSP →
        ``/gpSP`` subdir; the NULL ROM resolves to the default mGBA → ``/mGBA``.
        The save dir flips on the per-game override alone — proving the per-core
        layout keys off the same core the ROM launches with, not a platform default.
        """
        active_core = FakeActiveCoreResolver(
            default=("mgba_libretro", "mGBA"),
            per_rom={42: ("gpsp_libretro", "gpSP")},
        )
        svc, _ = make_service(
            tmp_path,
            active_core=active_core,
            # The .info corename mirrors the ES-DE label here for test simplicity.
            get_core_name=lambda core_so: "gpSP" if core_so == "gpsp_libretro" else "mGBA",
        )
        _install_rom(svc, tmp_path, rom_id=42, system="gba", file_name="pinned.gba")
        _install_rom(svc, tmp_path, rom_id=43, system="gba", file_name="default.gba")
        _set_sort_settings(svc, {"sort_by_content": True, "sort_by_core": True})

        pinned = svc._rom_info.get_rom_save_info(42)
        plain = svc._rom_info.get_rom_save_info(43)

        assert pinned is not None
        assert plain is not None
        assert pinned["saves_dir"].endswith("saves/gba/gpSP")
        assert plain["saves_dir"].endswith("saves/gba/mGBA")
        # Each ROM's save dir was resolved by its own rom_id.
        assert active_core.calls == [42, 43]

    def test_sort_by_core_uses_corename_not_es_de_label(self, tmp_path):
        """The RetroArch .info corename (``Snes9x``) must be used, not the ES-DE label (``Snes9x - Current``)."""
        svc, _ = make_service(
            tmp_path,
            active_core=FakeActiveCoreResolver(default=("snes9x_libretro", "Snes9x - Current")),
            get_core_name=lambda core_so: "Snes9x",
        )
        _install_rom(svc, tmp_path, system="snes", file_name="mario.sfc")
        _set_sort_settings(svc, {"sort_by_content": True, "sort_by_core": True})

        result = svc._rom_info.get_rom_save_info(42)

        assert result is not None
        assert result["saves_dir"].endswith("saves/snes/Snes9x")
        assert "Snes9x - Current" not in result["saves_dir"]

    def test_sort_by_core_falls_back_when_corename_none(self, tmp_path, caplog):
        """sort_by_core=True but corename unresolvable → warn + fall back to parent dir.

        The warning must include ``core_so=mgba_libretro`` so a user can identify
        which ``.info`` file the parser failed on.
        """
        svc, _ = make_service(
            tmp_path,
            active_core=FakeActiveCoreResolver(default=("mgba_libretro", "mGBA")),
            get_core_name=lambda core_so: None,  # .info unreadable / field missing
        )
        _install_rom(svc, tmp_path)
        _set_sort_settings(svc, {"sort_by_content": True, "sort_by_core": True})

        with caplog.at_level("WARNING"):
            result = svc._rom_info.get_rom_save_info(42)

        assert result is not None
        assert result["saves_dir"].endswith("saves/gba")
        assert "/mGBA" not in result["saves_dir"]
        warnings = [rec.message for rec in caplog.records if "unable to resolve RetroArch corename" in rec.message]
        assert warnings, "expected fallback warning"
        assert "core_so=mgba_libretro" in warnings[0]

    def test_sort_by_core_falls_back_when_get_core_name_returns_none(self, tmp_path, caplog):
        """``get_core_name`` returns ``None`` (.info unreadable) → warns and falls back.

        the resolver succeeded so ``core_so`` is identified in the
        diagnostic log to help the user locate the unreadable .info file.
        """
        svc, _ = make_service(
            tmp_path,
            active_core=FakeActiveCoreResolver(default=("mgba_libretro", "mGBA")),
            get_core_name=lambda core_so: None,
        )
        _install_rom(svc, tmp_path)
        _set_sort_settings(svc, {"sort_by_content": True, "sort_by_core": True})

        with caplog.at_level("WARNING"):
            result = svc._rom_info.get_rom_save_info(42)

        assert result is not None
        assert result["saves_dir"].endswith("saves/gba")
        warnings = [rec.message for rec in caplog.records if "unable to resolve RetroArch corename" in rec.message]
        assert warnings, "expected fallback warning"
        assert "core_so=mgba_libretro" in warnings[0]

    def test_sort_by_core_falls_back_when_active_core_unresolved(self, tmp_path, caplog):
        """sort_by_core=True but the resolver returns (None, None) → warn + fall back.

        When ES-DE cannot determine the active core, ``core_so`` is ``None`` and
        the log records ``core_so=unresolved``.
        """
        svc, _ = make_service(
            tmp_path,
            active_core=FakeActiveCoreResolver(default=(None, None)),
            get_core_name=lambda core_so: "mGBA",
        )
        _install_rom(svc, tmp_path)
        _set_sort_settings(svc, {"sort_by_content": True, "sort_by_core": True})

        with caplog.at_level("WARNING"):
            result = svc._rom_info.get_rom_save_info(42)

        assert result is not None
        assert result["saves_dir"].endswith("saves/gba")
        warnings = [rec.message for rec in caplog.records if "unable to resolve RetroArch corename" in rec.message]
        assert warnings, "expected fallback warning"
        assert "core_so=unresolved" in warnings[0]

    def test_resolve_retroarch_corename_happy_path(self, tmp_path):
        """Direct test of the helper: both seams resolve → (corename, core_so) tuple returned."""
        svc, _ = make_service(
            tmp_path,
            active_core=FakeActiveCoreResolver(default=("snes9x_libretro", "Snes9x - Current")),
            get_core_name=lambda core_so: "Snes9x",
        )
        assert svc._rom_info.resolve_retroarch_corename(42) == ("Snes9x", "snes9x_libretro")

    def test_resolve_retroarch_corename_returns_none_tuple_when_core_so_empty(self, tmp_path):
        """The resolver returns (None, None) → helper returns (None, None)."""
        svc, _ = make_service(
            tmp_path,
            active_core=FakeActiveCoreResolver(default=(None, None)),
            get_core_name=lambda core_so: "Snes9x",
        )
        assert svc._rom_info.resolve_retroarch_corename(42) == (None, None)

    def test_resolve_retroarch_corename_preserves_core_so_when_corename_empty(self, tmp_path):
        """Empty corename with resolved core_so → (None, core_so).

        The core_so is preserved in the second element so the caller can log
        which ``.info`` file failed diagnostically. The first element is None
        because the empty-string corename is treated as "no usable value".
        """
        svc, _ = make_service(
            tmp_path,
            active_core=FakeActiveCoreResolver(default=("snes9x_libretro", "Snes9x")),
            get_core_name=lambda core_so: "",
        )
        assert svc._rom_info.resolve_retroarch_corename(42) == (None, "snes9x_libretro")


class TestStandaloneSaveSetSelection:
    """The ROM's save set comes from its launch emulator, gated on the backend locating the folder."""

    def test_melonds_selects_its_folder_and_exact_name(self, tmp_path):
        svc, _, saves_dir = make_standalone_service(tmp_path, "melonds", system="nds", file_name="Mario Kart DS.nds")
        info = svc._rom_info.get_rom_save_info(42)
        assert info is not None
        assert info["saves_dir"] == str(saves_dir)
        assert info["save_set"].emulator_tag == "melonds"
        assert info["save_set"].filenames == ("Mario Kart DS.sav",)

    def test_duckstation_selects_two_cards(self, tmp_path):
        svc, _, _ = make_standalone_service(tmp_path, "duckstation", system="psx", file_name="Tekken 3.chd")
        info = svc._rom_info.get_rom_save_info(42)
        assert info is not None
        assert info["save_set"].filenames == ("Tekken 3_1.mcd", "Tekken 3_2.mcd")

    def test_vita3k_needs_a_title_id_launch_file(self, tmp_path):
        svc, _, saves_dir = make_standalone_service(tmp_path, "vita3k", system="psvita", file_name="PCSE01274.psvita")
        info = svc._rom_info.get_rom_save_info(42)
        assert info is not None
        assert info["saves_dir"] == str(saves_dir)
        assert info["save_set"].filenames == ("PCSE01274.vita3k.zip",)

    def test_vita3k_without_title_id_stem_keeps_retroarch_handling(self, tmp_path):
        svc, _, _ = make_standalone_service(tmp_path, "vita3k", system="psvita", file_name="Persona 3.vpk")
        info = svc._rom_info.get_rom_save_info(42)
        assert info is not None
        assert info["save_set"] is None
        assert info["saves_dir"].startswith(str(tmp_path / "saves"))

    def test_libretro_core_keeps_retroarch_handling(self, tmp_path):

        paths = FakeRetroDeckPaths(saves=str(tmp_path / "saves"), roms=str(tmp_path / "retrodeck" / "roms"))
        paths.standalone_saves["duckstation"] = str(tmp_path / "emu")
        svc, _ = make_service(
            tmp_path, launcher_paths=paths, active_core=FakeActiveCoreResolver(default=("swanstation_libretro", "SS"))
        )
        _install_rom(svc, tmp_path, system="psx", file_name="Tekken 3.chd")
        info = svc._rom_info.get_rom_save_info(42)
        assert info is not None
        assert info["save_set"] is None
        assert info["saves_dir"] == str(tmp_path / "saves" / "psx")

    def test_backend_without_standalone_root_never_resolves_the_emulator(self, tmp_path):

        active = FakeActiveCoreResolver(
            default_emulator=EmulatorInvocation.standalone(STANDALONE_COMMANDS["melonds"], "melonDS")
        )
        svc, _ = make_service(tmp_path, active_core=active)
        _install_rom(svc, tmp_path, system="nds", file_name="Mario Kart DS.nds")
        info = svc._rom_info.get_rom_save_info(42)
        assert info is not None
        assert info["save_set"] is None
        assert active.emulator_calls == []  # Linux/RetroDECK path: no extra resolution

    def test_unrecognised_standalone_keeps_retroarch_handling(self, tmp_path):

        paths = FakeRetroDeckPaths(saves=str(tmp_path / "saves"))
        paths.standalone_saves["melonds"] = str(tmp_path / "emu")
        active = FakeActiveCoreResolver(
            default_emulator=EmulatorInvocation.standalone('"C:\\tools\\pcsx2\\pcsx2-qt.exe"', "PCSX2")
        )
        svc, _ = make_service(tmp_path, launcher_paths=paths, active_core=active)
        _install_rom(svc, tmp_path, system="ps2", file_name="Game.iso")
        info = svc._rom_info.get_rom_save_info(42)
        assert info is not None
        assert info["save_set"] is None


class TestFindStandaloneSaveFiles:
    def test_melonds_finds_only_the_exact_name(self, tmp_path):
        svc, _, saves_dir = make_standalone_service(tmp_path, "melonds", system="nds", file_name="Mario Kart DS.nds")
        (saves_dir / "Mario Kart DS.sav").write_bytes(b"s")
        (saves_dir / "Mario Kart DS.dsv").write_bytes(b"d")
        (saves_dir / "Mario Kart DS (USA).sav").write_bytes(b"o")

        assert [f["filename"] for f in svc._rom_info.find_save_files(42)] == ["Mario Kart DS.sav"]

    def test_duckstation_ignores_a_card_named_differently(self, tmp_path):
        svc, _, saves_dir = make_standalone_service(
            tmp_path, "duckstation", system="psx", file_name="R4 - Ridge Racer Type 4 (USA).chd"
        )
        (saves_dir / "R4 - Ridge Racer Type 4 (USA)_1.mcd").write_bytes(b"1")
        (saves_dir / "R4 - Ridge Racer Type 4_2.mcd").write_bytes(b"x")
        (saves_dir / "shared_card_1.mcd").write_bytes(b"x")

        assert [f["filename"] for f in svc._rom_info.find_save_files(42)] == ["R4 - Ridge Racer Type 4 (USA)_1.mcd"]

    def test_vita_folder_is_packed_into_its_bundle(self, tmp_path):
        svc, _, saves_dir = make_standalone_service(tmp_path, "vita3k", system="psvita", file_name="PCSE01274.psvita")
        (saves_dir / "PCSE01274").mkdir()
        (saves_dir / "PCSE01274" / "SlotParam_0.bin").write_bytes(b"slot")
        (saves_dir / "PCSE00023").mkdir()  # another game's save: never touched
        (saves_dir / "PCSE00023" / "system.bin").write_bytes(b"other")

        files = svc._rom_info.find_save_files(42)

        assert files == [{"path": str(saves_dir / "PCSE01274.vita3k.zip"), "filename": "PCSE01274.vita3k.zip"}]
        with zipfile.ZipFile(saves_dir / "PCSE01274.vita3k.zip") as zf:
            assert zf.namelist() == ["SlotParam_0.bin"]
        assert not (saves_dir / "PCSE00023.vita3k.zip").exists()

    def test_vita_without_folder_has_no_local_save(self, tmp_path):
        svc, _, saves_dir = make_standalone_service(tmp_path, "vita3k", system="psvita", file_name="PCSE01274.psvita")
        (saves_dir / "PCSE01274.vita3k.zip").write_bytes(b"stale")  # derived leftover, folder gone
        assert svc._rom_info.find_save_files(42) == []

    def test_expected_save_files_stays_on_the_retroarch_projection(self, tmp_path):
        svc, _, _ = make_standalone_service(tmp_path, "melonds", system="nds", file_name="Mario Kart DS.nds")
        expected = svc._rom_info.expected_save_files(42)
        assert expected
        assert all(item["saves_dir"] == str(tmp_path / "saves" / "nds") for item in expected)


class TestUploadEmulatorTag:
    def test_standalone_tag(self, tmp_path):
        svc, _, _ = make_standalone_service(tmp_path, "duckstation", system="psx", file_name="Tekken 3.chd")
        assert svc._rom_info.upload_emulator_tag(42, None) == "duckstation"

    def test_retroarch_tag(self, tmp_path):
        svc, _ = make_service(tmp_path)
        _install_rom(svc, tmp_path)
        assert svc._rom_info.upload_emulator_tag(42, "mgba_libretro") == "retroarch-mgba"
        assert svc._rom_info.upload_emulator_tag(42, None) == "retroarch"
        assert svc._rom_info.upload_emulator_tag(999, "mgba_libretro") == "retroarch-mgba"


class TestDiscCodeSaveSetSelection:
    """Dolphin, PPSSPP and PCSX2 save sets come from the installed image's disc code."""

    def test_dolphin_reads_the_installed_image_as_a_nintendo_disc(self, tmp_path):
        from domain.disc_ids import NINTENDO_OPTICAL, DiscCode

        svc, _, saves_dir = make_standalone_service(
            tmp_path, "dolphin", system="gc", file_name="Soulcalibur II.rvz", disc=DiscCode("gc", "GRSEAF")
        )
        info = svc._rom_info.get_rom_save_info(42)
        assert info is not None
        assert info["saves_dir"] == str(saves_dir)
        assert info["save_set"].filenames == ("GRSEAF.dolphin-gc.zip",)
        reader = svc._rom_info._disc_codes
        assert isinstance(reader, FakeDiscCodeReader)
        assert reader.calls and reader.calls[-1] == (info["file_path"], NINTENDO_OPTICAL)
        assert info["file_path"].endswith("Soulcalibur II.rvz")

    def test_unidentified_disc_keeps_retroarch_handling(self, tmp_path):
        svc, _, _ = make_standalone_service(tmp_path, "ppsspp", system="psp", file_name="Game.pbp")
        info = svc._rom_info.get_rom_save_info(42)
        assert info is not None
        assert info["save_set"] is None
        assert info["saves_dir"].startswith(str(tmp_path / "saves"))

    def test_member_bundle_is_packed_by_find_save_files(self, tmp_path):
        from domain.disc_ids import DiscCode

        svc, _, saves_dir = make_standalone_service(
            tmp_path, "ppsspp", system="psp", file_name="Game.cso", disc=DiscCode("psp", "ULUS10234")
        )
        assert svc._rom_info.find_save_files(42) == []
        (saves_dir / "saves" / "ULUS10234DATA00").mkdir(parents=True)
        (saves_dir / "saves" / "ULUS10234DATA00" / "DATA.BIN").write_bytes(b"d")
        files = svc._rom_info.find_save_files(42)
        assert files == [{"path": str(saves_dir / "ULUS10234.ppsspp.zip"), "filename": "ULUS10234.ppsspp.zip"}]
        with zipfile.ZipFile(files[0]["path"]) as zf:
            assert zf.namelist() == ["ULUS10234DATA00/DATA.BIN"]

    def test_wii_data_folder_is_packed(self, tmp_path):
        from domain.disc_ids import DiscCode

        svc, _, saves_dir = make_standalone_service(
            tmp_path, "dolphin", system="wii", file_name="g.rvz", disc=DiscCode("wii", "SMOXE8")
        )
        data = saves_dir / "Wii" / "title" / "00010000" / "534d4f58" / "data"
        data.mkdir(parents=True)
        (data / "save.bin").write_bytes(b"s")
        assert [f["filename"] for f in svc._rom_info.find_save_files(42)] == ["SMOX.dolphin-wii.zip"]

    def test_pcsx2_reads_the_card_from_the_ini_beside_the_executable(self, tmp_path):
        from domain.disc_ids import DiscCode

        exe_dir = tmp_path / "PCSX2"
        (exe_dir / "inis").mkdir(parents=True)
        (exe_dir / "inis" / "PCSX2.ini").write_text("[MemoryCards]\nSlot1_Enable = true\nSlot1_Filename = folder.ps2\n")
        svc, _, saves_dir = make_standalone_service(
            tmp_path,
            "pcsx2",
            system="ps2",
            file_name="g.chd",
            disc=DiscCode("ps2", "SLUS-20062"),
            command=f'"{exe_dir / "pcsx2-qt.exe"}"',
        )
        (saves_dir / "saves" / "folder.ps2").mkdir(parents=True)
        (saves_dir / "saves" / "folder.ps2" / "_pcsx2_superblock").write_bytes(b"sb")
        info = svc._rom_info.get_rom_save_info(42)
        assert info is not None
        (source,) = info["save_set"].entries[0].layout.sources
        assert source.directory == "saves/folder.ps2"

    def test_upload_tag_is_the_emulator_id(self, tmp_path):
        from domain.disc_ids import DiscCode

        svc, _, _ = make_standalone_service(
            tmp_path, "ppsspp", system="psp", file_name="Game.cso", disc=DiscCode("psp", "ULUS10234")
        )
        assert svc._rom_info.upload_emulator_tag(42, "ppsspp_libretro") == "ppsspp"
