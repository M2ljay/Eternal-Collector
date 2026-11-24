/*
 * launch_command.h — the text handling of rom-launcher.exe, kept free of any
 * Windows call so it compiles and is tested on any host (test_launch_command.c).
 *
 * Command-line rules are the Windows C runtime's: the program name (argv[0])
 * ends at the next `"` when it starts with one, otherwise at the first space or
 * tab; there are no escapes inside it.
 */
#ifndef ROM_LAUNCHER_LAUNCH_COMMAND_H
#define ROM_LAUNCHER_LAUNCH_COMMAND_H

#include <stddef.h>
#include <wchar.h>

typedef enum {
    LC_OK = 0,          /* cmd.command is ready to run */
    LC_NO_COMMAND,      /* nothing after the launcher's own name */
    LC_NEEDS_TITLE_ID,  /* read cmd.title_id_file, then lc_apply_title_id */
} LcResult;

typedef struct {
    wchar_t *command;        /* full emulator command line, writable */
    wchar_t *directory;      /* emulator's folder, or "" to inherit */
    wchar_t *title_id_file;  /* set only for LC_NEEDS_TITLE_ID */
    size_t command_cap;      /* capacity of command, in wchar_t */
} LcCommand;

/* Buffer size (in wchar_t) lc_parse needs for a command line of len chars. */
#define LC_BUF_CHARS(len) (3 * ((len) + 64))

static const wchar_t LC_TITLE_ID_FLAG[] = L"--title-id-file";

static inline size_t lc_len(const wchar_t *s) {
    size_t n = 0;
    while (s[n])
        n++;
    return n;
}

static inline int lc_is_space(wchar_t c) { return c == L' ' || c == L'\t'; }

static inline void lc_ulong_to_wstr(unsigned long v, wchar_t out[16]) {
    wchar_t tmp[16];
    int n = 0;
    do {
        tmp[n++] = (wchar_t)(L'0' + v % 10);
        v /= 10;
    } while (v && n < 15);
    for (int i = 0; i < n; i++)
        out[i] = tmp[n - 1 - i];
    out[n] = 0;
}

static const wchar_t *lc_skip_program_name(const wchar_t *p) {
    if (*p == L'"') {
        p++;
        while (*p && *p != L'"')
            p++;
        if (*p == L'"')
            p++;
    } else {
        while (*p && !lc_is_space(*p))
            p++;
    }
    while (lc_is_space(*p))
        p++;
    return p;
}

static inline void lc_copy(wchar_t *dst, const wchar_t *src, size_t n) {
    for (size_t i = 0; i < n; i++)
        dst[i] = src[i];
    dst[n] = 0;
}

/* Folder of the command's first token (the emulator exe), or "" without one. */
static inline void lc_directory_of(const wchar_t *command, wchar_t *out) {
    const wchar_t *start = command, *end;
    if (*start == L'"') {
        start++;
        end = start;
        while (*end && *end != L'"')
            end++;
    } else {
        end = start;
        while (*end && !lc_is_space(*end))
            end++;
    }
    const wchar_t *slash = NULL;
    for (const wchar_t *q = start; q < end; q++)
        if (*q == L'\\' || *q == L'/')
            slash = q;
    if (!slash) {
        out[0] = 0;
        return;
    }
    size_t n = (size_t)(slash - start);
    if (n == 2 && start[1] == L':')  /* "C:\x.exe" -> "C:\" */
        n = 3;
    lc_copy(out, start, n);
}

static inline int lc_starts_with_flag(const wchar_t *p) {
    size_t n = lc_len(LC_TITLE_ID_FLAG);
    for (size_t i = 0; i < n; i++)
        if (p[i] != LC_TITLE_ID_FLAG[i])
            return 0;
    return lc_is_space(p[n]);
}

/*
 * Splits the launcher's full command line into the emulator command, its
 * folder, and (for --title-id-file) the game file to read the ID from.
 * buf must hold LC_BUF_CHARS(lc_len(full)) wchar_t.
 */
static inline LcResult lc_parse(const wchar_t *full, wchar_t *buf, LcCommand *cmd) {
    size_t len = lc_len(full);
    size_t region = len + 64;
    cmd->command = buf;
    cmd->directory = buf + region;
    cmd->title_id_file = buf + 2 * region;
    cmd->command_cap = region;
    cmd->command[0] = cmd->directory[0] = cmd->title_id_file[0] = 0;

    const wchar_t *rest = lc_skip_program_name(full);
    size_t n = lc_len(rest);
    while (n > 0 && lc_is_space(rest[n - 1]))
        n--;
    if (n == 0)
        return LC_NO_COMMAND;

    if (!lc_starts_with_flag(rest)) {
        lc_copy(cmd->command, rest, n);
        lc_directory_of(cmd->command, cmd->directory);
        return LC_OK;
    }

    rest += lc_len(LC_TITLE_ID_FLAG);
    while (lc_is_space(*rest)) {
        rest++;
        n--;
    }
    n -= lc_len(LC_TITLE_ID_FLAG);
    /* The game file is the trailing quoted argument. */
    if (n < 2 || rest[n - 1] != L'"')
        return LC_NO_COMMAND;
    size_t open = n - 1;
    while (open > 0 && rest[open - 1] != L'"')
        open--;
    if (open == 0)
        return LC_NO_COMMAND;
    open--; /* index of the opening quote */
    lc_copy(cmd->title_id_file, rest + open + 1, n - open - 2);
    size_t keep = open;
    while (keep > 0 && lc_is_space(rest[keep - 1]))
        keep--;
    if (keep == 0)
        return LC_NO_COMMAND;
    lc_copy(cmd->command, rest, keep);
    lc_directory_of(cmd->command, cmd->directory);
    return LC_NEEDS_TITLE_ID;
}

/* A Vita title ID: four capital letters, five digits (PCSE00000). */
static inline int lc_is_title_id(const wchar_t *s, size_t n) {
    if (n != 9)
        return 0;
    for (size_t i = 0; i < 4; i++)
        if (s[i] < L'A' || s[i] > L'Z')
            return 0;
    for (size_t i = 4; i < 9; i++)
        if (s[i] < L'0' || s[i] > L'9')
            return 0;
    return 1;
}

/*
 * Appends " <ID>" to cmd->command from the raw file text (surrounding
 * whitespace and a UTF-8 byte-order mark tolerated). Returns 0 when the text
 * holds no title ID.
 */
static inline int lc_apply_title_id(LcCommand *cmd, const wchar_t *raw) {
    const wchar_t *s = raw;
    if (s[0] == 0xEF && s[1] == 0xBB && s[2] == 0xBF)
        s += 3;
    while (*s && (lc_is_space(*s) || *s == L'\r' || *s == L'\n'))
        s++;
    size_t n = lc_len(s);
    while (n > 0 && (lc_is_space(s[n - 1]) || s[n - 1] == L'\r' || s[n - 1] == L'\n'))
        n--;
    if (!lc_is_title_id(s, n))
        return 0;
    size_t at = lc_len(cmd->command);
    if (at + 1 + n + 1 > cmd->command_cap)
        return 0;
    cmd->command[at] = L' ';
    lc_copy(cmd->command + at + 1, s, n);
    return 1;
}

/* Steam's Big Picture window: "Steam Big Picture Mode". */
static inline int lc_is_big_picture_title(const wchar_t *title) {
    static const wchar_t want[] = L"Steam Big Picture Mode";
    size_t w = lc_len(want), n = lc_len(title);
    for (size_t i = 0; i + w <= n; i++) {
        size_t k = 0;
        while (k < w && title[i + k] == want[k])
            k++;
        if (k == w)
            return 1;
    }
    return 0;
}

#endif
