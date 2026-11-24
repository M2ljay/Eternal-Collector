/* Host-side tests for launch_command.h. Cases are taken from real launches
 * recorded in rom-launcher.log. Run via build.sh. */
#include <stdio.h>
#include <stdlib.h>

#include "launch_command.h"

static int failures = 0;

static void expect_str(const char *what, const wchar_t *got, const wchar_t *want) {
    size_t i = 0;
    while (got[i] && got[i] == want[i])
        i++;
    if (got[i] != want[i]) {
        failures++;
        printf("FAIL %s\n  got:  %ls\n  want: %ls\n", what, got, want);
    }
}

static void expect_int(const char *what, int got, int want) {
    if (got != want) {
        failures++;
        printf("FAIL %s: got %d want %d\n", what, got, want);
    }
}

static wchar_t *buffer_for(const wchar_t *full) {
    return calloc(LC_BUF_CHARS(lc_len(full)), sizeof(wchar_t));
}

static void test_retroarch(void) {
    const wchar_t *full =
        L"\"C:\\Users\\M2lJa\\homebrew\\plugins\\romm-dock\\bin\\rom-launcher.exe\" "
        L"\"C:\\Users\\M2lJa\\AppData\\Roaming\\emudeck\\Emulators\\RetroArch\\retroarch.exe\" "
        L"-L C:\\Users\\M2lJa\\AppData\\Roaming\\emudeck\\Emulators\\RetroArch\\cores\\mesen_libretro.dll "
        L"\"C:\\Emulation\\roms\\nes\\Super Mario Bros. 2.nes\"";
    wchar_t *buf = buffer_for(full);
    LcCommand c;
    expect_int("retroarch result", lc_parse(full, buf, &c), LC_OK);
    expect_str("retroarch command", c.command,
               L"\"C:\\Users\\M2lJa\\AppData\\Roaming\\emudeck\\Emulators\\RetroArch\\retroarch.exe\" "
               L"-L C:\\Users\\M2lJa\\AppData\\Roaming\\emudeck\\Emulators\\RetroArch\\cores\\mesen_libretro.dll "
               L"\"C:\\Emulation\\roms\\nes\\Super Mario Bros. 2.nes\"");
    expect_str("retroarch dir", c.directory, L"C:\\Users\\M2lJa\\AppData\\Roaming\\emudeck\\Emulators\\RetroArch");
    free(buf);
}

static void test_vita_unquoted_exe(void) {
    const wchar_t *full =
        L"\"C:\\Users\\M2lJa\\homebrew\\plugins\\romm-dock\\bin\\rom-launcher.exe\" --title-id-file "
        L"C:\\Users\\M2lJa\\AppData\\Roaming\\emudeck\\Emulators\\vita3k\\vita3k.exe -F -r "
        L"\"C:\\Emulation\\roms\\psvita\\Persona 3 Dancing in Moonlight.psvita\"";
    wchar_t *buf = buffer_for(full);
    LcCommand c;
    expect_int("vita result", lc_parse(full, buf, &c), LC_NEEDS_TITLE_ID);
    expect_str("vita file", c.title_id_file, L"C:\\Emulation\\roms\\psvita\\Persona 3 Dancing in Moonlight.psvita");
    expect_int("vita apply", lc_apply_title_id(&c, L"PCSE01274\r\n"), 1);
    expect_str("vita command", c.command,
               L"C:\\Users\\M2lJa\\AppData\\Roaming\\emudeck\\Emulators\\vita3k\\vita3k.exe -F -r PCSE01274");
    expect_str("vita dir", c.directory, L"C:\\Users\\M2lJa\\AppData\\Roaming\\emudeck\\Emulators\\vita3k");
    free(buf);
}

static void test_vita_quoted_exe(void) {
    const wchar_t *full =
        L"\"C:\\x\\bin\\rom-launcher.exe\" --title-id-file "
        L"\"C:\\Users\\M2lJa\\AppData\\Roaming\\emudeck\\Emulators\\vita3k\\vita3k.exe\" -F -r "
        L"\"C:\\Emulation\\roms\\psvita\\J-Stars Victory VS+\\PCSE00595.psvita\"";
    wchar_t *buf = buffer_for(full);
    LcCommand c;
    expect_int("vita2 result", lc_parse(full, buf, &c), LC_NEEDS_TITLE_ID);
    expect_str("vita2 file", c.title_id_file, L"C:\\Emulation\\roms\\psvita\\J-Stars Victory VS+\\PCSE00595.psvita");
    expect_int("vita2 apply (BOM)", lc_apply_title_id(&c, L"\xEF\xBB\xBFPCSE00595"), 1);
    expect_str("vita2 command", c.command,
               L"\"C:\\Users\\M2lJa\\AppData\\Roaming\\emudeck\\Emulators\\vita3k\\vita3k.exe\" -F -r PCSE00595");
    free(buf);
}

static void test_bad_title_id(void) {
    const wchar_t *full = L"rom-launcher.exe --title-id-file C:\\v\\vita3k.exe -r \"C:\\g.psvita\"";
    wchar_t *buf = buffer_for(full);
    LcCommand c;
    expect_int("bad result", lc_parse(full, buf, &c), LC_NEEDS_TITLE_ID);
    expect_int("bad id rejected", lc_apply_title_id(&c, L"not an id"), 0);
    expect_int("lowercase rejected", lc_apply_title_id(&c, L"pcse00595"), 0);
    expect_int("empty rejected", lc_apply_title_id(&c, L""), 0);
    free(buf);
}

static void test_no_command(void) {
    const wchar_t *cases[] = {
        L"\"C:\\x\\bin\\rom-launcher.exe\"",
        L"\"C:\\x\\bin\\rom-launcher.exe\"   ",
        L"rom-launcher.exe",
        L"rom-launcher.exe --title-id-file C:\\v\\vita3k.exe -r",
        L"rom-launcher.exe --title-id-file \"C:\\g.psvita\"",
    };
    for (size_t i = 0; i < sizeof cases / sizeof *cases; i++) {
        wchar_t *buf = buffer_for(cases[i]);
        LcCommand c;
        char what[32];
        snprintf(what, sizeof what, "no-command case %zu", i);
        expect_int(what, lc_parse(cases[i], buf, &c), LC_NO_COMMAND);
        free(buf);
    }
}

static void test_bare_exe_inherits_directory(void) {
    const wchar_t *full = L"rom-launcher.exe retroarch.exe -L core.dll \"game.nes\"";
    wchar_t *buf = buffer_for(full);
    LcCommand c;
    expect_int("bare result", lc_parse(full, buf, &c), LC_OK);
    expect_str("bare dir", c.directory, L"");
    expect_str("bare command", c.command, L"retroarch.exe -L core.dll \"game.nes\"");
    free(buf);
}

static void test_drive_root_exe(void) {
    const wchar_t *full = L"x.exe \"C:\\emu.exe\" \"D:\\g.iso\"";
    wchar_t *buf = buffer_for(full);
    LcCommand c;
    lc_parse(full, buf, &c);
    expect_str("root dir", c.directory, L"C:\\");
    free(buf);
}

static void test_big_picture_title(void) {
    expect_int("bpm exact", lc_is_big_picture_title(L"Steam Big Picture Mode"), 1);
    expect_int("bpm other", lc_is_big_picture_title(L"Steam"), 0);
    expect_int("bpm empty", lc_is_big_picture_title(L""), 0);
}

int main(void) {
    test_retroarch();
    test_vita_unquoted_exe();
    test_vita_quoted_exe();
    test_bad_title_id();
    test_no_command();
    test_bare_exe_inherits_directory();
    test_drive_root_exe();
    test_big_picture_title();
    if (failures) {
        printf("%d failure(s)\n", failures);
        return 1;
    }
    printf("launch_command: all tests passed\n");
    return 0;
}
