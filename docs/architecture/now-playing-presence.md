# Now playing: the running ROM for other plugins (Discord Rich Presence)

While a RomM game launched through its Steam shortcut is running, The Collector publishes a small "now playing" record:
the ROM's title, its console, when the session started and the shortcut's app id, plus a cover URL when one is safe to
show. Assemble, the Discord plugin, reads it and shows "Playing _The Legend of Zelda: Ocarina of Time_ · Nintendo 64"
instead of the shortcut name or the emulator. Any other plugin may read it. Neither plugin depends on the other: without
a reader the record is unused, and without The Collector there is no record. The user-facing description is in
[Managing Games](../user-guide/managing-games.md#discord-shows-the-game-you-are-playing).

## The record

Version 1 of the document, identical in both places described below:

```json
{
  "v": 1,
  "source": "collector",
  "records": {
    "3000000123": {
      "app_id": 3000000123,
      "rom_id": 42,
      "name": "The Legend of Zelda: Ocarina of Time",
      "platform": "Nintendo 64",
      "started_at": 1764190000000,
      "cover_url": "https://images.igdb.com/igdb/image/upload/t_cover_big/co3nnx.jpg"
    }
  }
}
```

- One record per running RomM game, keyed by the shortcut's Steam app id as a string. Two games at once are two records.
- `name` and `platform` are single-line display strings of at most 128 characters. `platform` is the console's display
  name from the offline platform-name cache, else the RomM slug.
- `started_at` is the session's start in Unix milliseconds — the same instant the session manager attests, so a reload
  mid-game keeps the elapsed time.
- `cover_url` is `null` or a public URL (below).
- Readers must ignore unknown fields and any other `v`. A breaking change bumps `v`.

The shape and its rules live in `domain/now_playing.py`.

## Where it is published, and why two places

Decky runs every plugin's frontend in Steam's one shared JavaScript context, but each plugin's backend is a separate
process with its own settings and data folders. So the record is published twice:

1. **On the Steam window.** `window.__eternalNowPlaying` holds the document, and an `eternal_now_playing` event is
   dispatched on `window` after every change (`src/utils/nowPlayingPublisher.ts`). This is the main path: immediate,
   with no file access, and it survives the reader plugin reloading on its own, because the object stays on the window.
   The property is deleted when no game runs.
2. **In a file**, `<Decky home>/data/eternal-now-playing/now-playing.json` (`services/now_playing.py`, written through
   `adapters/now_playing_file.py`, path chosen in `bootstrap/adapters.py` as the sibling of this plugin's runtime
   folder). `data/` is the one place every plugin backend can reach. The file is for a reader's backend: Assemble reads
   it only when its frontend had no record, and only a record that started during the current Steam session of that app.
   Writes go to a temporary file renamed over the old one, so a reader never sees half a document. The file is removed
   when no game runs, and deleted when the backend starts (a session cannot be live yet; the frontend's reload adoption
   republishes the games still running).

A file alone would need the reader to poll and would have no "it changed" signal; a window object alone would be out of
reach of a reader's backend. The record is only shown for the Steam app id it names, so a stale entry cannot be attached
to another game.

## Lifecycle

The publisher follows `sessionManager` through its `romm_session_changed` event and never changes when or how a session
is tracked. The event's `startMs` is the session's attested start.

- **Start** (a new session, or one restored by reload adoption): `publish_now_playing(rom_id, app_id, started_at_ms)`
  reads the ROM's name and platform from SQLite, writes the record without a cover and answers it; the publisher puts it
  on the window. Then `resolve_now_playing_cover(rom_id, app_id)` asks RomM once, with the short probe timeout, for the
  ROM's `url_cover`, and adds it when it is public. RomM being unreachable only means no cover.
- **Re-announcement** of a live session: ignored, the record is already out.
- **Stop**: the record leaves the window at once and `clear_now_playing(app_id)` removes it from the file.
- **Plugin unload**: every record is withdrawn.

A game that ends while its publish is in flight is never shown again: the publisher drops an answer that belongs to an
older session edge, and the backend serialises every read-modify-write of the file behind one lock, so a clear sent
after a publish lands after it.

Nothing here can affect play. Every failure is logged and leaves the record out.

## Covers: never the RomM server

The record leaves the plugin — another plugin sends it to Discord — so nothing in it may point at the RomM server or
carry a credential. `cover_url` is only ever:

- the ROM's external `url_cover` from RomM's API (the metadata provider's own image), never a RomM asset path
  (`path_cover_*`, which would expose the server address and needs the bearer token);
- `https`, on a public metadata CDN (IGDB, SteamGridDB, MobyGames, LaunchBox, RetroAchievements: `PUBLIC_COVER_HOSTS`);
- without user info, port, query or fragment. ScreenScraper media URLs carry the account in their query and are refused.

Anything else is `null`. Discord itself only shows an outside image through a Discord application's external assets, so
Assemble uses the cover only when the title matches a game Discord knows; otherwise the activity is text only.
