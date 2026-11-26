import { FC, useCallback, useEffect, useRef, useState } from "react";
import { DialogButton, Focusable, useParams } from "@decky/ui";
import { getConsoleGames, logWarn, refreshConsoleAchievements } from "../../api/backend";
import type { ConsoleGame, ConsoleGamesPage } from "../../types";
import { mediaKindFor } from "../../utils/consoleMedia";
import { pluralize } from "../../utils/pluralize";
import { COLLECTOR_CSS } from "./collectorStyles";
import { GameCase } from "./GameCase";

export const PAGE_SIZE = 100;
export const CASES_PER_ROW = 6;
/** The achievement snapshot is re-read from RomM when a page opens and it is older than this. */
export const ACHIEVEMENTS_MAX_AGE_MS = 3_600_000;

interface PageState {
  status: "loading" | "ready" | "error";
  meta: Omit<ConsoleGamesPage, "games"> | null;
  games: ConsoleGame[];
  message: string;
}

const LOADING: PageState = { status: "loading", meta: null, games: [], message: "" };

function chunk<T>(items: T[], size: number): T[][] {
  const rows: T[][] = [];
  for (let i = 0; i < items.length; i += size) rows.push(items.slice(i, i + size));
  return rows;
}

export function snapshotIsStale(fetchedAt: string | null, now: number = Date.now()): boolean {
  if (!fetchedAt) return true;
  const at = Date.parse(fetchedAt);
  return Number.isNaN(at) || now - at > ACHIEVEMENTS_MAX_AGE_MS;
}

/**
 * The console page route: the console's games in its media style, "Continue" (the
 * most recently played game) first, each with its save-sync and RetroAchievements
 * chips. Selecting a game opens the game page, which owns Play.
 *
 * Every answer is bound to the slug and the read that asked for it: a reply for a
 * console the page has since left, or an older read for the same console, is dropped.
 */
export const ConsolePage: FC = () => {
  const { slug: rawSlug } = useParams<{ slug?: string }>();
  const slug = decodeURIComponent(rawSlug ?? "");
  return <ConsolePageBody key={slug} slug={slug} />;
};

const ConsolePageBody: FC<{ slug: string }> = ({ slug }) => {
  const [state, setState] = useState<PageState>(LOADING);
  const seq = useRef(0);
  const refreshTried = useRef<string | null>(null);

  const load = useCallback(
    async (offset: number, limit: number, replace: boolean) => {
      const ticket = ++seq.current;
      try {
        const answer = await getConsoleGames(slug, offset, limit);
        if (ticket !== seq.current) return null;
        if (!answer.success) {
          setState((s) => ({ ...s, status: s.games.length ? "ready" : "error", message: answer.message }));
          return null;
        }
        const { games, ...meta } = answer;
        setState((s) => ({ status: "ready", meta, games: replace ? games : [...s.games, ...games], message: "" }));
        return answer;
      } catch (e) {
        if (ticket !== seq.current) return null;
        const message = e instanceof Error ? e.message : String(e);
        logWarn(`The Collector: console page read failed for ${slug}: ${message}`);
        setState((s) => ({
          ...s,
          status: s.games.length ? "ready" : "error",
          message: "Could not load this console.",
        }));
        return null;
      }
    },
    [slug],
  );

  useEffect(() => {
    let alive = true;
    const stillHere = () => alive;
    void (async () => {
      const first = await load(0, PAGE_SIZE, true);
      if (!stillHere() || !first || refreshTried.current === slug) return;
      if (!snapshotIsStale(first.achievements_fetched_at) || !first.games.some((g) => g.has_ra_set)) return;
      refreshTried.current = slug;
      try {
        const refreshed = await refreshConsoleAchievements();
        if (stillHere() && refreshed.success) await load(0, PAGE_SIZE, true);
      } catch (e) {
        logWarn(`The Collector: achievement refresh failed: ${e instanceof Error ? e.message : String(e)}`);
      }
    })();
    return () => {
      alive = false;
      seq.current += 1;
    };
  }, [slug, load]);

  const kind = mediaKindFor(slug);
  const { meta, games } = state;
  const continueGame = meta?.continue_rom_id != null && games[0]?.rom_id === meta.continue_rom_id ? games[0] : null;
  const rest = continueGame ? games.slice(1) : games;
  const saveSyncEnabled = meta?.save_sync_enabled ?? false;

  return (
    <div className="tc-page" data-collector-page={slug}>
      <style>{COLLECTOR_CSS}</style>
      <div className="tc-page__head">
        <h1 className="tc-page__title">{meta?.name ?? slug}</h1>
        {meta && <span className="tc-page__count">{pluralize(meta.total, "game")}</span>}
      </div>
      {state.status === "loading" && <div className="tc-page__status">Loading…</div>}
      {state.status === "error" && (
        <div className="tc-page__status" role="status">
          {state.message || "Could not load this console."}
        </div>
      )}
      {state.status === "ready" && games.length === 0 && (
        <div className="tc-page__status" role="status">
          No games from this console are in Steam.
        </div>
      )}
      {continueGame && (
        <>
          <div className="tc-page__section">Continue</div>
          <Focusable flow-children="row" className="tc-grid__row">
            <GameCase game={continueGame} kind={kind} saveSyncEnabled={saveSyncEnabled} continueCase preferredFocus />
          </Focusable>
        </>
      )}
      {rest.length > 0 && (
        <>
          <div className="tc-page__section">All games</div>
          <Focusable flow-children="column" className="tc-grid">
            {chunk(rest, CASES_PER_ROW).map((row, index) => (
              <Focusable key={row[0]!.rom_id} flow-children="row" className="tc-grid__row">
                {row.map((game, column) => (
                  <GameCase
                    key={game.rom_id}
                    game={game}
                    kind={kind}
                    saveSyncEnabled={saveSyncEnabled}
                    preferredFocus={!continueGame && index === 0 && column === 0}
                  />
                ))}
              </Focusable>
            ))}
          </Focusable>
        </>
      )}
      {meta && games.length < meta.total && (
        <div className="tc-more">
          <DialogButton onClick={() => void load(games.length, PAGE_SIZE, false)}>
            Show more ({meta.total - games.length} left)
          </DialogButton>
        </div>
      )}
    </div>
  );
};
