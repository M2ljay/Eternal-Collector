/*
 * launch_policy.h — when rom-launcher.exe keeps waiting, asks the game to
 * close, or ends; free of any Windows call so test_launch_command.c covers it.
 *
 * The launcher is the process Steam starts and tracks. It lives exactly as
 * long as anything in its job object does, so Steam sees the game running for
 * as long as the emulator (or a process the emulator handed off to) is up, and
 * nothing outlives it: when the launcher ends, by itself or because Steam ended
 * it, Windows closes the job and kills whatever is still inside.
 *
 * A close request (Steam's Exit Game reaching the launcher as WM_CLOSE, or the
 * session ending) is passed on politely first: WM_CLOSE to the emulator's own
 * windows, so it can save and quit. If it is still running after
 * LP_CLOSE_GRACE_MS, the launcher ends and the job takes it down.
 */
#ifndef ROM_LAUNCHER_LAUNCH_POLICY_H
#define ROM_LAUNCHER_LAUNCH_POLICY_H

/* Long enough for an emulator to flush a memory card or a save file, short
   enough that Exit Game never looks stuck. */
#define LP_CLOSE_GRACE_MS 10000U

typedef enum {
    LP_WAIT = 0,   /* keep waiting */
    LP_ASK_CLOSE,  /* post WM_CLOSE to the job's windows, once */
    LP_END,        /* stop waiting; closing the job ends anything left */
} LpAction;

typedef struct {
    int asked;               /* WM_CLOSE has been passed on */
    unsigned int asked_at;   /* tick count when it was (32-bit, like GetTickCount) */
} LpState;

/* The next step, given how many processes the job still holds, whether a
   close has been requested, and the current tick count (wrap-safe). */
static inline LpAction lp_next(LpState *s, unsigned long job_active, int close_requested, unsigned int now) {
    if (job_active == 0)
        return LP_END;
    if (close_requested && !s->asked) {
        s->asked = 1;
        s->asked_at = now;
        return LP_ASK_CLOSE;
    }
    if (s->asked && (unsigned int)(now - s->asked_at) >= LP_CLOSE_GRACE_MS)
        return LP_END;
    return LP_WAIT;
}

#endif
