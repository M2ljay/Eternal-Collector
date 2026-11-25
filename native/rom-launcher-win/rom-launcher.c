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
 *   4b. While the emulator starts and while it shuts down, covers the screen
 *      with the Core logo so its menu window never flashes up; the curtain is
 *      down whenever the game is fullscreen (see the curtain section).
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

/* ------------------------------------------------------------- curtain -- */

/* Emulators show their own menu window, or an unpainted white render window,
   for a moment before the game goes fullscreen, and their menu again while
   they shut down. A click-through, never-focused window showing the Core mark
   on true black covers the screen from launch and lifts once the emulator has
   had, for CURTAIN_SETTLE_MS without a break, a borderless window covering the
   whole monitor with none of its title-bar windows (its menu) in front of it.
   When that window goes away while the emulator lives on, the curtain comes
   back until the emulator exits and Big Picture is in front again. The
   emulator's own windows may also be topmost, and a newer topmost window
   lands above an older one, so the curtain re-asserts its place on every
   tick. It lifts after CURTAIN_MAX_MS at launch, or CURTAIN_EXIT_MAX_MS after
   the game left fullscreen without quitting, so it can never hide a game that
   runs windowed for longer than that. */

#define CURTAIN_MAX_MS 8000
#define CURTAIN_SETTLE_MS 800
#define CURTAIN_EXIT_MAX_MS 4000

#define CURTAIN_LOGO_ID 101 /* rom-launcher.rc */
#define CURTAIN_BLACK RGB(0, 0, 0) /* AMOLED black */

/* True black with the Core mark centred, a fifth of the screen's height. */
static void curtain_paint(HWND hwnd) {
    PAINTSTRUCT ps;
    HDC dc = BeginPaint(hwnd, &ps);
    RECT r;
    GetClientRect(hwnd, &r);
    HBRUSH black = CreateSolidBrush(CURTAIN_BLACK);
    FillRect(dc, &r, black);
    DeleteObject(black);
    HBITMAP logo = LoadBitmapW(GetModuleHandleW(NULL), MAKEINTRESOURCEW(CURTAIN_LOGO_ID));
    if (logo) {
        BITMAP bm;
        GetObjectW(logo, sizeof bm, &bm);
        int h = (r.bottom - r.top) / 5;
        int w = bm.bmHeight ? h * bm.bmWidth / bm.bmHeight : h;
        int x = (r.right - r.left - w) / 2, y = (r.bottom - r.top - h) / 2;
        HDC mem = CreateCompatibleDC(dc);
        HGDIOBJ old = SelectObject(mem, logo);
        SetStretchBltMode(dc, HALFTONE);
        SetBrushOrgEx(dc, 0, 0, NULL);
        StretchBlt(dc, x, y, w, h, mem, 0, 0, bm.bmWidth, bm.bmHeight, SRCCOPY);
        SelectObject(mem, old);
        DeleteDC(mem);
        DeleteObject(logo);
    }
    EndPaint(hwnd, &ps);
}

static LRESULT CALLBACK curtain_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    if (msg == WM_NCHITTEST)
        return HTTRANSPARENT;
    if (msg == WM_MOUSEACTIVATE)
        return MA_NOACTIVATE;
    if (msg == WM_ERASEBKGND)
        return 1;
    if (msg == WM_PAINT) {
        curtain_paint(hwnd);
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

static RECT curtain_monitor(void) {
    FindBpm ctx = {NULL};
    EnumWindows(find_bpm, (LPARAM)&ctx);
    POINT origin = {0, 0};
    HMONITOR mon = ctx.found ? MonitorFromWindow(ctx.found, MONITOR_DEFAULTTOPRIMARY)
                             : MonitorFromPoint(origin, MONITOR_DEFAULTTOPRIMARY);
    MONITORINFO mi;
    mi.cbSize = sizeof mi;
    RECT r = {0, 0, GetSystemMetrics(SM_CXSCREEN), GetSystemMetrics(SM_CYSCREEN)};
    if (GetMonitorInfoW(mon, &mi))
        r = mi.rcMonitor;
    return r;
}

static HWND curtain_raise(RECT mon) {
    WNDCLASSW wc;
    for (SIZE_T i = 0; i < sizeof wc; i++)
        ((char *)&wc)[i] = 0;
    wc.lpfnWndProc = curtain_proc;
    wc.hInstance = GetModuleHandleW(NULL);
    wc.lpszClassName = L"RomLauncherCurtain";
    RegisterClassW(&wc);
    HWND w = CreateWindowExW(WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT,
                             wc.lpszClassName, L"", WS_POPUP, mon.left, mon.top, mon.right - mon.left,
                             mon.bottom - mon.top, NULL, NULL, wc.hInstance, NULL);
    if (w) {
        ShowWindow(w, SW_SHOWNOACTIVATE);
        UpdateWindow(w);
        log_line(L"curtain up", NULL);
    }
    return w;
}

typedef struct {
    HANDLE job;
    HWND curtain;
    RECT mon;
    BOOL found;    /* a borderless job window covers the monitor, frontmost */
    BOOL menu_up;  /* a job window with a title bar is in front of it */
} FindGame;

static BOOL in_job(HWND hwnd, HANDLE job) {
    DWORD pid = 0;
    GetWindowThreadProcessId(hwnd, &pid);
    HANDLE p = pid ? OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid) : NULL;
    if (!p)
        return FALSE;
    BOOL inside = FALSE;
    IsProcessInJob(p, job, &inside);
    CloseHandle(p);
    return inside;
}

static BOOL CALLBACK find_game(HWND hwnd, LPARAM lp) {
    FindGame *ctx = (FindGame *)lp;
    if (hwnd == ctx->curtain || !IsWindowVisible(hwnd) || GetWindow(hwnd, GW_OWNER) != NULL)
        return TRUE;
    LONG style = GetWindowLongW(hwnd, GWL_STYLE);
    if (style & WS_MINIMIZE)
        return TRUE;
    BOOL captioned = (style & WS_CAPTION) == WS_CAPTION;
    RECT r;
    BOOL covers = !captioned && GetWindowRect(hwnd, &r) && r.left <= ctx->mon.left && r.top <= ctx->mon.top &&
                  r.right >= ctx->mon.right && r.bottom >= ctx->mon.bottom;
    if (!captioned && !covers)
        return TRUE;
    if (!in_job(hwnd, ctx->job))
        return TRUE;
    /* EnumWindows walks the z-order front to back: a menu window counts only
       if it sits in front of the game, not left open behind it. */
    if (captioned && !ctx->found)
        ctx->menu_up = TRUE;
    else if (!captioned && !ctx->menu_up)
        ctx->found = TRUE;
    return TRUE;
}

static void pump_messages(void) {
    MSG m;
    while (PeekMessageW(&m, NULL, 0, 0, PM_REMOVE)) {
        TranslateMessage(&m);
        DispatchMessageW(&m);
    }
}

/* Waits for the emulator and returns the curtain if it is still up (the
   caller lifts it after Big Picture is back in front, so the desktop never
   shows in between). The curtain is up while the emulator starts, down while
   its game is fullscreen, and back up when the game's fullscreen window goes
   away while the process lives on: emulators show their menu window again
   while they shut down. If the game was only leaving fullscreen, not
   quitting, the curtain lifts again after CURTAIN_EXIT_MAX_MS. */
static HWND wait_with_curtain(HANDLE process, HANDLE job) {
    if (!job) {
        WaitForSingleObject(process, INFINITE);
        return NULL;
    }
    RECT mon = curtain_monitor();
    HWND curtain = curtain_raise(mon);
    DWORD start = GetTickCount();
    DWORD seen_at = 0, raised_at = start;
    BOOL playing = FALSE;  /* the game has been fullscreen at least once */
    for (;;) {
        DWORD r = MsgWaitForMultipleObjects(1, &process, FALSE, 50, QS_ALLINPUT);
        pump_messages();
        if (r == WAIT_OBJECT_0)
            break;
        DWORD now = GetTickCount();
        FindGame ctx = {job, curtain, mon, FALSE, FALSE};
        EnumWindows(find_game, (LPARAM)&ctx);
        BOOL game_up = ctx.found && !ctx.menu_up;
        if (curtain) {
            SetWindowPos(curtain, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
            if (game_up) {
                if (!seen_at)
                    seen_at = now;
            } else {
                seen_at = 0;
            }
            DWORD limit = playing ? CURTAIN_EXIT_MAX_MS : CURTAIN_MAX_MS;
            if ((seen_at && now - seen_at >= CURTAIN_SETTLE_MS) || now - raised_at >= limit) {
                log_line(seen_at ? L"curtain down: game is fullscreen" : L"curtain down: timed out", NULL);
                DestroyWindow(curtain);
                pump_messages();
                curtain = NULL;
                playing = playing || seen_at != 0;
                seen_at = 0;
            }
        } else if (playing && !ctx.found) {
            curtain = curtain_raise(mon);
            raised_at = now;
            log_line(L"curtain up: game left fullscreen", NULL);
        }
    }
    WaitForSingleObject(process, INFINITE);
    if (!curtain) {
        /* Exited straight from fullscreen: cover the gap until Big Picture is back. */
        curtain = curtain_raise(mon);
    }
    return curtain;
}

/* ---------------------------------------------------------------- main -- */

static void log_error(const wchar_t *msg) {
    log_number(msg, GetLastError());
}

static int run(void) {
    SetProcessDPIAware();
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

    HWND curtain = wait_with_curtain(pi.hProcess, job);
    DWORD code = 0;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hProcess);
    log_number(L"emulator exited with code ", code);

    refocus_big_picture();
    if (curtain) {
        Sleep(150);
        DestroyWindow(curtain);
        log_line(L"curtain down: back in Big Picture", NULL);
    }
    if (job)
        CloseHandle(job);
    return (int)code;
}

/* A GUI-subsystem program, so no console window flashes up when Steam
   starts a game. Its only window is the launch curtain. */
int WINAPI WinMain(HINSTANCE inst, HINSTANCE prev, LPSTR args, int show) {
    (void)inst;
    (void)prev;
    (void)args;
    (void)show;
    return run();
}

