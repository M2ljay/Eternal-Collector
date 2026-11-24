/*
 * rom-launcher.exe — Windows Steam shortcut launcher for RomM-Dock.
 *
 * The Windows counterpart of bin/rom-launcher (a bash `exec "$@"`). Steam runs
 * every RomM shortcut as `rom-launcher.exe <launch options>`, where the launch
 * options are the emulator command the plugin baked (quoted per the C runtime
 * rules, see quote_windows_arg in adapters/emudeck_windows_launcher_backend.py).
 *
 * What it does, in order:
 *   1. Takes everything after its own name on the command line, verbatim. No
 *      re-quoting: the emulator receives exactly the text the plugin wrote.
 *   2. `--title-id-file <command> "<file>"`: replaces the trailing quoted path
 *      with the PS Vita title ID that file holds (Vita3K runs `-r PCSE00000`,
 *      the library keeps ES-DE-style `<TITLE_ID>.psvita` files).
 *   3. Starts the emulator suspended, in its own folder, inside a job object
 *      that kills it when this process goes away — so Steam's "Stop game",
 *      which ends the shortcut's process, also ends the emulator.
 *   4. Waits, then returns the emulator's exit code to Steam.
 *   5. Puts the Steam Big Picture window back in front: an emulator quitting
 *      to the desktop otherwise leaves Big Picture behind other windows.
 *
 * Every step is logged to rom-launcher.log next to the exe.
 *
 * Exit codes: the emulator's own; 1 = no command; 2 = no usable title ID;
 * 3 = the process could not be started.
 *
 * Build and test (any host): native/rom-launcher-win/build.sh
 */

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include "launch_command.h"

/* ------------------------------------------------------------------ log -- */

static HANDLE g_log = INVALID_HANDLE_VALUE;

static void log_open(void) {
    wchar_t path[MAX_PATH + 32];
    DWORD n = GetModuleFileNameW(NULL, path, MAX_PATH);
    if (n == 0 || n >= MAX_PATH)
        return;
    while (n > 0 && path[n - 1] != L'\\' && path[n - 1] != L'/')
        n--;
    const wchar_t *name = L"rom-launcher.log";
    for (int i = 0; name[i]; i++)
        path[n++] = name[i];
    path[n] = 0;
    g_log = CreateFileW(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_ALWAYS,
                        FILE_ATTRIBUTE_NORMAL, NULL);
    if (g_log != INVALID_HANDLE_VALUE)
        SetFilePointer(g_log, 0, NULL, FILE_END);
}

static void log_write_utf8(const wchar_t *text, int len) {
    if (g_log == INVALID_HANDLE_VALUE || len <= 0)
        return;
    int bytes = WideCharToMultiByte(CP_UTF8, 0, text, len, NULL, 0, NULL, NULL);
    if (bytes <= 0)
        return;
    char *buf = HeapAlloc(GetProcessHeap(), 0, (SIZE_T)bytes);
    if (!buf)
        return;
    WideCharToMultiByte(CP_UTF8, 0, text, len, buf, bytes, NULL, NULL);
    DWORD written;
    WriteFile(g_log, buf, (DWORD)bytes, &written, NULL);
    HeapFree(GetProcessHeap(), 0, buf);
}

/* "<YYYY-MM-DD HH:MM:SS> <msg><detail>\r\n"; detail may be NULL. */
static void log_line(const wchar_t *msg, const wchar_t *detail) {
    SYSTEMTIME t;
    GetLocalTime(&t);
    wchar_t stamp[24];
    int v[6] = {t.wYear, t.wMonth, t.wDay, t.wHour, t.wMinute, t.wSecond};
    const wchar_t *sep = L"--  ::";
    int p = 0;
    for (int i = 0; i < 6; i++) {
        int digits = i == 0 ? 4 : 2;
        for (int d = digits - 1; d >= 0; d--) {
            int x = v[i];
            for (int k = 0; k < d; k++)
                x /= 10;
            stamp[p++] = (wchar_t)(L'0' + x % 10);
        }
        stamp[p++] = i < 5 ? sep[i] : L' ';
    }
    log_write_utf8(stamp, p);
    log_write_utf8(msg, (int)lc_len(msg));
    if (detail)
        log_write_utf8(detail, (int)lc_len(detail));
    log_write_utf8(L"\r\n", 2);
}

static void log_number(const wchar_t *msg, unsigned long value) {
    wchar_t digits[16];
    lc_ulong_to_wstr(value, digits);
    log_line(msg, digits);
}

/* ------------------------------------------------------- title-id file -- */

/* Reads up to cap-1 bytes of an ASCII file into a wide buffer. */
static int read_small_file(const wchar_t *path, wchar_t *out, int cap) {
    HANDLE f = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (f == INVALID_HANDLE_VALUE)
        return -1;
    char buf[64];
    DWORD got = 0;
    BOOL ok = ReadFile(f, buf, sizeof buf - 1, &got, NULL);
    CloseHandle(f);
    if (!ok)
        return -1;
    int n = 0;
    for (DWORD i = 0; i < got && n < cap - 1; i++)
        out[n++] = (wchar_t)(unsigned char)buf[i];
    out[n] = 0;
    return n;
}

/* ------------------------------------------------------------- refocus -- */

typedef struct {
    HWND found;
} FindBpm;

static BOOL CALLBACK find_bpm(HWND hwnd, LPARAM lp) {
    FindBpm *ctx = (FindBpm *)lp;
    if (!IsWindowVisible(hwnd) || GetWindow(hwnd, GW_OWNER) != NULL)
        return TRUE;
    wchar_t title[128];
    int n = GetWindowTextW(hwnd, title, 128);
    if (n <= 0 || !lc_is_big_picture_title(title))
        return TRUE;
    RECT r;
    if (GetWindowRect(hwnd, &r) && r.right > r.left && r.bottom > r.top) {
        ctx->found = hwnd;
        return FALSE;
    }
    return TRUE;
}

static void refocus_big_picture(void) {
    FindBpm ctx = {NULL};
    EnumWindows(find_bpm, (LPARAM)&ctx);
    if (!ctx.found) {
        log_line(L"Steam Big Picture window not found to refocus", NULL);
        return;
    }
    /* Windows only lets the foreground thread hand focus over; attaching to it
       borrows that right for the call. */
    HWND fg = GetForegroundWindow();
    DWORD fg_thread = fg ? GetWindowThreadProcessId(fg, NULL) : 0;
    DWORD me = GetCurrentThreadId();
    BOOL attached = fg_thread && fg_thread != me && AttachThreadInput(me, fg_thread, TRUE);
    DWORD bpm_pid = 0;
    GetWindowThreadProcessId(ctx.found, &bpm_pid);
    if (bpm_pid)
        AllowSetForegroundWindow(bpm_pid);
    BringWindowToTop(ctx.found);
    BOOL ok = SetForegroundWindow(ctx.found);
    if (attached)
        AttachThreadInput(me, fg_thread, FALSE);
    log_line(ok ? L"brought window to front" : L"could not bring window to front", NULL);
}

/* ---------------------------------------------------------------- main -- */

static void log_error(const wchar_t *msg) {
    log_number(msg, GetLastError());
}

static int run(void) {
    log_open();
    const wchar_t *full = GetCommandLineW();
    log_line(L"start: ", full);

    LcCommand cmd;
    wchar_t *heap = HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, LC_BUF_CHARS(lc_len(full)) * sizeof(wchar_t));
    if (!heap)
        return 3;

    LcResult r = lc_parse(full, heap, &cmd);
    if (r == LC_NO_COMMAND) {
        log_line(L"no emulator command in launch options (exit 1)", NULL);
        return 1;
    }
    if (r == LC_NEEDS_TITLE_ID) {
        wchar_t id[64];
        if (read_small_file(cmd.title_id_file, id, 64) < 0) {
            log_line(L"cannot open title ID file ", cmd.title_id_file);
            log_line(L"no usable title ID in the game file (exit 2)", NULL);
            return 2;
        }
        if (!lc_apply_title_id(&cmd, id)) {
            log_line(L"no usable title ID in the game file (exit 2)", NULL);
            return 2;
        }
    }

    log_line(L"run: ", cmd.command);
    log_line(L"in: ", cmd.directory[0] ? cmd.directory : L"(inherited)");

    HANDLE job = CreateJobObjectW(NULL, NULL);
    if (job) {
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION lim;
        for (SIZE_T i = 0; i < sizeof lim; i++)
            ((char *)&lim)[i] = 0;
        lim.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        SetInformationJobObject(job, JobObjectExtendedLimitInformation, &lim, sizeof lim);
    }

    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    for (SIZE_T i = 0; i < sizeof si; i++)
        ((char *)&si)[i] = 0;
    si.cb = sizeof si;
    /* CreateProcessW may write into the command buffer; cmd.command is ours. */
    if (!CreateProcessW(NULL, cmd.command, NULL, NULL, FALSE, CREATE_SUSPENDED, NULL,
                        cmd.directory[0] ? cmd.directory : NULL, &si, &pi)) {
        log_error(L"CreateProcess failed, Windows error ");
        return 3;
    }
    if (job && !AssignProcessToJobObject(job, pi.hProcess))
        log_error(L"job assign failed, Windows error ");
    ResumeThread(pi.hThread);
    CloseHandle(pi.hThread);
    log_number(L"started pid ", pi.dwProcessId);

    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 0;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hProcess);
    log_number(L"emulator exited with code ", code);

    refocus_big_picture();
    if (job)
        CloseHandle(job);
    return (int)code;
}

/* A GUI-subsystem program, so no console window flashes up when Steam
   starts a game. It never creates a window of its own. */
int WINAPI WinMain(HINSTANCE inst, HINSTANCE prev, LPSTR args, int show) {
    (void)inst;
    (void)prev;
    (void)args;
    (void)show;
    return run();
}

