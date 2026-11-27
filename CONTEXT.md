# CONTEXT.md — RomM-Dock domain glossary

This file is a glossary. It defines the canonical meaning of project-specific terms so that conversations, issues, PRs,
and code stay aligned. It is _not_ a spec or design doc — implementation docs live in `docs/architecture/`, and
architectural decisions live in `docs/adr/`.

When a term resolves during a discussion, it gets added here. When a term's meaning changes, the entry gets rewritten —
not appended to.

## Terms

### Aggregate

A cluster of domain objects treated as a single unit for data consistency. Per Cosmic Python chapters 1–7:

- Has **one root** entity (a dataclass) that is the only external entry point.
- Enforces all of its own **invariants** — outside code cannot violate them.
- Is the **transaction boundary**: saved atomically as a unit.
- Has exactly one **identity**. Other aggregates reference it by ID only, never by holding a Python reference to its
  internals.
- Mutation is **only via methods on the root**, named after the domain event that occurred (`adopt_baseline(...)`,
  `confirm_slot(...)`, `mark_installed(...)`). Direct field assignment from services is forbidden.
- Has exactly **one Repository** Protocol. The Repository's job is "give me this aggregate by ID, save this aggregate" —
  it may touch multiple tables under the hood.

What an aggregate is _not_: a DTO sent to the frontend, a query projection, or "stuff that happens to live in the same
file." Aggregate boundaries are **invariant boundaries**, not storage boundaries.

Chapters 8+ of the CP book (domain events + message bus) are explicitly out of scope. Triggers for revisiting that scope
are documented in `CLAUDE.md`. The concrete aggregate set, its tables, and the enforcement layers live in
`docs/architecture/database-design.md` — this entry defines the term, not the inventory.

### Value Object

An immutable member of an aggregate, built whole and never mutated in place — a `@dataclass(frozen=True, slots=True)`,
not a `@cosmic_aggregate` root. It has no identity of its own and no mutation surface to police, so it carries neither
the decorator nor the verb-method discipline an aggregate root does. `FileSyncState` (inside `RomSaveSyncState`) is the
canonical example. The foil to **Aggregate**: a root has identity and methods; a value object has neither.

### Repository

The single persistence seam for one **Aggregate** — "give me this aggregate by id, save this aggregate." Exactly one
Repository per aggregate root (Protocol in `services/protocols/`, SQLite adapter behind it). It may touch several tables
to reconstruct or persist the aggregate — the `RomSaveSyncState` repository spans `rom_save_sync_states` +
`rom_save_files` — but callers see only `get(id)` / `save(id, aggregate)`. It _is_ the load/save layer; the service
layer never wraps it in a second one (no `StateService`-style holder between service and repository). Reached only
through the **Unit of Work** (`uow.rom_save_sync_states`, `uow.rom_installs`, …), never constructed directly.

### Unit of Work

The atomic transaction boundary one operation works inside, and the carrier of the **Repositories** for that
transaction. Owned by the service layer at the operation's entry (never by `main.py` callables); a `with uow:` block
opens one connection, exposes the repositories, and commits on clean exit / rolls back on exception (stdlib `sqlite3` +
`run_in_executor`, per [ADR-0004](docs/adr/0004-sync-sqlite-unit-of-work.md)). Kept **narrow** — it wraps only the
database reads/writes, never network/file I/O or a frontend round-trip; cross-operation consistency comes from the
operation's own serialization (the per-ROM save lock, the single library-sync task), not from holding a UoW open.

### Persistence boundary (settings.json / SQLite)

Where a piece of persisted state lives is a deliberate decision driven by what the data _is_, not which file it
historically lived in. Per [ADR-0003](docs/adr/0003-json-sqlite-persistence-boundary.md), three buckets, and the bucket
picks the store:

1. **User-intent config** — flat, no relationships, the user sets it → **`settings.json`**. Includes credentials, scalar
   toggles, the sync-selection lists (`enabled_platforms`, `enabled_collections`), the save-sync feature toggles
   (`save_sync_enabled`, `sync_before_launch`, `sync_after_exit`, `default_slot`, `autocleanup_limit`), and
   `device_name`.
2. **Observed / derived-from-an-external-source** — read, not set → **read live by default**; persisted (in `kv_config`)
   only as a last-seen marker for cross-run change detection. The RetroDECK home path and save-sort settings markers
   live here.
3. **Synced / derived relational state with real invariants** — per-ROM groups, history, caches of remote data →
   **SQLite aggregates**.

`device_id` now lives in the `kv_config` table; bucket-3 save state lives in SQLite aggregates. `save_sync_state.json`
is a dead store — never written, read exactly once at bootstrap for the one-time legacy settings fold. As of #822 it no
longer held the save-sync toggles or `device_name` (those moved to `settings.json`, settings schema v4).

### Cutover

The hard cut from JSON state files to SQLite ([#784](https://github.com/danielcopper/decky-romm-sync/issues/784)) has
landed. "Hard" means **SQLite started empty** — the JSON state was not migrated into it, and the JSON-era domain classes
(`SaveSyncState`, `PluginState`) and `domain/save_state.py` were deleted in the same wave. Bucket-1 config
(`settings.json`) and the change-detection markers were unaffected; only the relational save/library/playtime state was
re-derived from scratch (re-synced from RomM, re-pruned against disk).

### kv_config

A key-value table for small singleton configuration values that don't justify their own aggregate or table. One row per
key.

Residents (per [ADR-0003](docs/adr/0003-json-sqlite-persistence-boundary.md)): the RetroDECK home path marker
(`retrodeck_home_path` + its pending-migration `_previous`), the save-sort settings markers (`save_sort_settings` +
`_previous`), `device_id` (server-issued identity), `platform_names` (platform_slug → display_name cache), and
`steam_collections_adopted` (set once the one-time adoption of pre-record Steam collections is done). The schema version
is **not** a `kv_config` key — it lives in `PRAGMA user_version`.

**Not** a dumping ground: anything with its own lifecycle, invariants, or repeat-row potential gets its own aggregate.
`kv_config` is for the truly small, the truly singleton, and the truly miscellaneous.

### Rom (aggregate) vs ROM (file) vs RomM (server)

Three things spell similarly; distinct meanings:

- **Rom** — the aggregate / domain entity owned by this plugin (`domain/rom.py`). Represents one ROM as the plugin
  tracks it locally: identity, the denormalized `platform_slug`, sync metadata, the Steam shortcut binding.
- **ROM** (or "ROM file") — the actual playable game file on disk (e.g. `.iso`, `.cue`, `.gba`). What `RomInstall`
  records once a `Rom` has been downloaded.
- **RomM** — the upstream self-hosted server. The source of truth this plugin syncs _from_.

Convention: always write `Rom` (PascalCase) when referring to the aggregate. Write "ROM file" when referring to the
on-disk artifact.

### Version (RomM: sibling) vs Region / Languages

A **version** is one concrete released dump of a game — its own RomM `rom_id`, its own file, its own save universe
(saves never carry across versions; matches RomM's per-ROM saves and RetroArch's per-content save naming). All versions
of one game form a **sibling group** (RomM's `sibling_roms`: same matched metadata id, per platform; unmatched ROMs are
solo groups). Key derivation: `domain/sibling_group.py`, persisted as `roms.sibling_group_key`
([ADR-0021](docs/adr/0021-sibling-group-one-shortcut-binding-active-version.md)).

- **Active version** — the sibling currently bound to the group's Steam shortcut (`roms.shortcut_app_id`); the one that
  installs, launches, and syncs saves. Binding = active version (ADR-0021).
- **Default version** — RomM's per-user `is_main_sibling` ("SET DEFAULT" in RomM's Switch-version UI). Optional;
  respected read-only as a preselect, never written back.
- **Switch version** — the user-facing control (named after RomM's) that changes the active version within a group;
  rendered only when the group has more than one version (#1297/#1298).

**Region** and **Languages** are **attributes of a single version**, parsed from its filename tags: `(Spain)` → where
that release shipped; `(En,Fr,De,Es)` → the languages contained in that one dump. A multi-language version is still one
version. UI rule: Region/Languages render on the game-detail page for the active version only — they are never a version
list and never the switch mechanism.

### file_path vs rom_dir (RomInstall paths)

The two path fields on `RomInstall` (`domain/rom_install.py`) answer different questions and must not be conflated:

- **`file_path`** — the **launch file**: the single file that is the ROM's launch identity. Present for every ROM;
  save-path resolution, ES-DE core resolution, and the displayed filename all derive from it. It is the **default**
  launch target baked into the Steam shortcut's `launch_options` (`flatpak run … "<file_path>"`, run by the
  `rom-launcher` exec wrapper per [ADR-0009](docs/adr/0009-launcher-pure-exec-wrapper-baked-launch-options.md), which
  superseded the dynamic SQLite read of [ADR-0005](docs/adr/0005-launcher-resolves-path-from-sqlite.md)) — but the baked
  launch **target** may be **overridden at bake time** without rewriting `file_path`: a multi-disc pin bakes the
  selected disc's path
  ([ADR-0014](docs/adr/0014-per-game-disc-selection-in-db-applied-as-bake-time-launch-path-override.md)), and a
  folder-boot system (PS3/RPCS3) bakes the game **directory** rather than the nested launch file
  ([ADR-0019](docs/adr/0019-folder-as-launch-target.md)). `file_path` stays the launch **file** anchor in every case.
- **`rom_dir`** — the **dedicated per-ROM directory**, present only for folder-backed (multi-file) ROMs. **NULL for
  single-file ROMs**, which live as a bare file directly in the shared `<roms>/<system>/` directory and own no dedicated
  folder.

Single-file vs multi-file is **read from `rom_dir` presence** — never re-derived from the file's parent directory, never
stored as a separate boolean ([ADR-0008](docs/adr/0008-rom-install-launch-file-and-rom-dir.md)). Migration moves
`rom_dir` whole when set, else the file; uninstall removes `rom_dir` whole when set, else the file. A future per-file
`RomFile[]` model — one row per physical file, each tagged with a RomM `category` (`game` / `dlc` / `update` / `mod` /
…) — is the planned shape for the multi-file features in
[#140](https://github.com/danielcopper/decky-romm-sync/issues/140) /
[#129](https://github.com/danielcopper/decky-romm-sync/issues/129); it is an additive 1:N child of `rom_installs`
(deferred until those land), and `file_path` + `rom_dir` are its forward-compatible projection.

### Launchable install / no launch target

A downloaded ROM whose recorded **launch file** is something the system cannot act on — a PS3 `.pkg` installer (the game
is still sealed inside the package), a bare disc track `.bin`. `detect_launch_file` ends in "largest file by size", so a
download none of its format rules recognise still yields a `file_path`; `RomInstall.launchable` records whether that
path is a real launch target, decided once at download-complete against the system's live ES-DE accept-list
([#1652](https://github.com/danielcopper/decky-romm-sync/issues/1652)).

"No launch target" is a statement about the **launch command**, never about the download. The files stay on disk, the
install row is written, and uninstall works normally — installing the package by hand in the emulator is the documented
RetroDECK procedure and a refusal that discarded the download would leave the user worse off. What is withheld is the
baked `launch_options`: an unlaunchable install resolves to the empty path in the `DiscLaunchResolver` seam, so every
bake site emits the same empty launch command an **un-downloaded** ROM's shortcut carries.

Unlaunchable is always a **proven** verdict, never the absence of one: an unreadable accept-list, an unknown system, and
a pre-migration row all read as launchable. The foil is a **folder-boot** install, whose `file_path` extension is
irrelevant because the baked target is the game directory.

### Adopt

To take something already present into the plugin's records without having produced it. The object varies — a local save
file becomes a tracked baseline (`adopt_baseline(...)`), a play session survives a frontend reload, an identity-only
claim picks up the debris of an interrupted removal
([ADR-0027](docs/adr/0027-claim-discipline-follows-the-recovery-bundle.md)), a ROM already on disk becomes an install —
but the rule does not: the recorded state derives from what was found, not from what the plugin did. _Avoid_: claim
(reserved for the removal machinery's authorization), import, link, register.

### Adopted install

A `rom_installs` row for content the plugin did not download. Indistinguishable from a downloaded one in every respect,
**including deletion authority**: uninstall and removed-game cleanup delete an adopted ROM's files exactly as they would
a downloaded ROM's. The protection therefore sits at the moment of adoption — proving the content is the ROM the row
will claim — never in a downstream exemption, because a second class of install row would need a second branch in every
consumer (uninstall, cleanup, home migration, version switch).

### Adoption candidate

An entry at the top level of the platform's ROM directory that no `rom_installs` row accounts for, whose shape matches
what the server serves, and whose **normalized name** equals the ROM's. "Candidate" carries the uncertainty
deliberately: a name says nothing about content, so until it is verified this is a guess — and what ranks one candidate
above another is only cheap evidence (a single-member archive's CRC32 from the ZIP index, an exact size), never proof.
The verification (CRC32/MD5, read from a ZIP's central directory where the content is archived) is always
user-triggered, never a wait imposed before the plugin will say anything.

### Entry kind

What an entry on disk **is**, judged by its own type without following it: `file`, `dir` or `link`. There is no fourth
value — anything else a filesystem can hold (a FIFO, a socket, a device node) gets no kind at all, because "file or
directory" has no truthful answer for one and inventing one is what let a named pipe be offered as a game. One rule
answers this for every read of the filesystem, and the two kinds of read differ only in what they do with a kindless
entry: a **directory listing** leaves it out, while **describing one named path** reports it with the kind absent —
something that is there must never come back as nothing, or the next write goes over it in silence. A `link` is its own
kind rather than whatever it resolves to: an install row must be removable, the uninstall path refuses a symlink, so a
link is never adoptable however well its target resolves. _Avoid_: "shape" for this — **shape** is the
single-file-vs-folder question the server answers, and the two are different judgements about different things.

### Unusable namesake

An entry whose **normalized name** equals the ROM's but which cannot become its install: the other **shape** — a
directory where RomM serves a single file, or a loose file where it serves a folder — or any `link`. It is deliberately
**not** an adoption candidate: nothing about it can be taken over, so it is never offered, ranked or renamed. It is
still reported, because the alternative is a download that silently produces a second copy of the game beside it. The
dialog's two exits are download-anyway (the server's copy lands beside it, under the server's name) and cancel; neither
touches the entry. The two reasons are not one reason: a wrong shape is wrong only against what the server sends, so
that refusal names the served shape, while a `link` is unusable on its own terms and naming a shape beside it would
suggest the other shape would have taken it. _Avoid_: mismatched candidate, unusable candidate — the whole point is that
it is not one.

### Normalized name

A ROM filename reduced to the game it denotes: extension removed, bracketed groups `(...)` / `[...]` dropped with their
contents, every run of non-alphanumerics collapsed to one space, lowercased, trimmed.
`Example Quest - Second Journey (Rev 1) (USA).zip` → `example quest second journey`. It is the candidate search's only
match key, applied identically to both sides. An empty normalization (a name that is nothing but tags) matches nothing
rather than everything. _Avoid_: fuzzy match, similar name — the comparison is exact equality of the normalized strings,
and no edit distance or token scoring is involved.

### platform_slug (denormalized)

The RomM platform identifier (e.g. `gba`, `psx`) carried as a plain string on the rows that need it (`roms`,
`rom_installs`, `downloaded_bios`, `firmware_cache`). There is **no local `Platform` aggregate** — that was proposed in
ADR-0001 and **dropped by [ADR-0003](docs/adr/0003-json-sqlite-persistence-boundary.md)** on YAGNI grounds. Platform
display names resolve live from RomM; sync exclusion is the user-intent `enabled_platforms` config in `settings.json`,
not per-platform local state. A `Platform` aggregate is reintroduced only when a concrete need lands (the
standalone-emulator roadmap), not speculatively.

### Emulator override vs default core vs active core

Three distinct notions in core selection, kept separate because they have different owners and lifetimes:

- **Default core** — the emulator RetroDECK declares for a platform (in `es_systems.xml`) — see **default emulator** for
  the precise selection rule, which may resolve to a RetroArch core **or** a standalone emulator. RetroDECK-owned; it
  can change on a RetroDECK update. The plugin reads it live and **never stores** it — a stored copy would go stale.
- **Emulator override** — a deliberate user choice to deviate from the default core, at **per-game** or **per-platform**
  scope. The plugin owns the override and stores **only the deviation**; the absence of an override means "follow the
  default." A core the user picks inside ES-DE's own UI is _not_ an emulator override in this sense — it is ES-DE's
  state, which the plugin does not own.
- **Active core** — the core a ROM actually launches with: the override when one exists, the default otherwise. One
  resolver answers it for both the launch and every read consumer (BIOS requirement, save path, game-detail badge), so
  the launched core never diverges from what those reads assume.

### Safely-bakeable

An ES-DE `<command>` the plugin can bake into a Steam shortcut's `-e` override: a real emulator invocation that **ends
in `%ROM%`** and carries none of the forms the bake can't carry — no `%INJECT%` sidecar (that is _needs-setup_, not
launchable from Steam until ES-DE has run it once), no `%ENABLESHORTCUTS%` / `%EMULATOR_OS-SHELL%` shortcut-script form,
no embedded quoting (`"` or `\;`), no `%STARTDIR%` (RetroDECK's `run_game.sh` parses-but-drops it), and no placeholder
outside the known whitelist. The classifier `domain/emulator_commands.py` decides this per command; anything not
safely-bakeable is surfaced in the picker as **disabled** with a reason, never silently offered
([ADR-0020](docs/adr/0020-live-es-systems-emulator-resolution.md)). The foil to **default emulator** (the first
safely-bakeable command a system falls back to).

### Default emulator

The emulator a ROM launches with absent any per-game or per-platform **emulator override**: the **first
_safely-bakeable_ command in a system's `es_systems.xml` document order**. ES-DE lists a system's emulators in
preference order, so ES-DE's own preference picks it — the plugin adds no curation. It may be a **RetroArch core** or a
**standalone emulator** (PCSX2, RPCS3, Dolphin, …), whichever ES-DE lists first that the plugin can bake. Resolved live
from the sole source (`es_systems.xml`) — there is no bundled snapshot (the curated `core_defaults.json` was deleted in
\#1210). When no command is safely-bakeable (or `es_systems.xml` can't be read) there is no default emulator and the ROM
plain-launches, letting RetroDECK resolve its own command
([ADR-0020](docs/adr/0020-live-es-systems-emulator-resolution.md)). The foil to **emulator override** (a user deviation
from this default).

### Launcher backend

Which app a ROM's launch command actually runs through — **RetroDECK** (the default) or **EmuDeck**. Orthogonal to
**default emulator** / **emulator override** / **active core**: those decide WHICH emulator a ROM resolves to, on any
backend; the launcher backend decides HOW that resolved emulator is rendered into an OS-executable command
(`LauncherBackend.resolve_invocation`, `services/protocols/launcher_backend.py`) AND WHERE downloads, BIOS files, and
saves live on disk (`LauncherBackend.roms_path`/`bios_path`/`saves_path`/`states_path`, consumed as `LauncherPaths` by
every file-placement service) — an EmuDeck-only machine with no RetroDECK installed works end-to-end once EmuDeck is the
active backend. Stored as the plugin's own deviation-free intent (`settings.json`'s `launcher_backend` /
`launcher_backend_installation`, bucket-1 per the persistence boundary) — there is no "no backend" state, RetroDECK is
the seeded default. Switching backends re-bakes every installed+bound shortcut's `launch_options` through the existing
per-platform-core-change fan-out mechanism (ADR-0009's confirmed `SetAppLaunchOptions`), never a shortcut
delete/recreate. See [Launcher Backends](docs/architecture/launcher-backends.md).

### Disc

The launchable unit of a multi-disc ROM: a single-disc **container** file the emulator opens directly — a `.cue`, a
`.chd`, or an `.iso` (`DISC_IMAGE_EXTENSIONS`, `domain/disc_formats.py`). A disc is **not** its `.bin` sidecar (raw
track data a `.cue` references, never launched directly) and **not** the `.m3u` playlist (which points at several
discs). When a bin/cue PS1 game ships both files, the disc is the `.cue`, never the `.bin`. The foil to **disc-image
format** (the file-shape category) and **selected disc** (the user's per-game pick among the discs).

### Disc-image format

The format-semantic, emulator-independent category "this file shape is a launchable disc image" — the hardcoded set
`{.cue, .chd, .iso}` (`DISC_IMAGE_EXTENSIONS`). It answers _is this a disc image?_, which es_systems cannot: es_systems
is a flat per-system accept-list with no per-token role metadata, so it can say a system _accepts_ `.cue` but never that
`.cue` is a disc while `.bin` is its sidecar. The set is intersected with the system's **live** es_systems accept-list
at enumeration time, so the hardcoded knowledge supplies disc _identity_ and es_systems supplies per-system _capability_
— two different questions with two different owners
([ADR-0014](docs/adr/0014-per-game-disc-selection-in-db-applied-as-bake-time-launch-path-override.md)).

### Selected disc

A user's per-game pick of **which disc launches** for a multi-disc ROM, stored as the disc's **basename** on
`roms.selected_disc` (nullable). It mirrors the per-game **emulator override** exactly: NULL means "follow the default"
(the install's `.m3u` when `file_path` is one, else the first enumerated disc), only `pin_selected_disc` /
`clear_selected_disc` write it, it is **excluded from the sync UPSERT** so a re-sync never resets it, and it anchors on
`roms` so it survives uninstall/reinstall and home migration. Applied as a **bake-time launch-path override** — it
changes only the path baked into the shortcut's `launch_options`, never `RomInstall.file_path`, structurally identical
to how the override changes the invocation without touching `file_path`
([ADR-0014](docs/adr/0014-per-game-disc-selection-in-db-applied-as-bake-time-launch-path-override.md)). A stale pin (the
disc no longer present) degrades to the default with a WARNING, never fatal.

### Save-sync slot

A named channel for a ROM's saves (e.g. `default`). **Every slot is a real, addressable name** — the active slot for a
ROM is recorded on its `RomSaveSyncState`, and `default_slot` (a `settings.json` config value, per #822) is the slot a
newly-tracked ROM starts on. Slots let the same ROM carry distinct save sets without clobbering one another. Confirming
a slot (`confirm_slot(...)`) is an explicit user/flow decision that requires a real slot name — the plugin never
silently adopts a foreign slot, and it never confirms a ROM onto the legacy `slot:null`. The legacy `slot:null` is
**retired as a confirmable target** (#1276 / ADR-0017): it survives only as a one-time migration **source** — the Slot
Setup Wizard migrates those pre-slot saves into a named slot — and is never a ROM's active slot.

### Standalone save set / save bundle / disc code

The exact, ROM-derived list of save files a **standalone emulator** keeps for one game (`domain/standalone_saves.py`):
melonDS `<stem>.sav`, DuckStation `<stem>_1.mcd` / `<stem>_2.mcd`, Vita3K the `<TITLE_ID>` folder. A ROM has one only
when it launches with that emulator and the active launcher backend locates the emulator's save folder (EmuDeck for
Windows today); otherwise its saves are RetroArch's. Dolphin, PPSSPP and PCSX2 sets are named by the **disc code** the
installed image carries (Dolphin's ID6, the PSP game ID, the PS2 boot serial — `domain/disc_ids.py`) rather than the ROM
stem; an image that cannot be read exactly has no set. Never a guess — a file not selected by an exact rule is not in
the set. A **save bundle** is a save that is not one file travelling as one deterministic zip: a **folder bundle**
(`<TITLE_ID>.vita3k.zip`, `<ID4>.dolphin-wii.zip`) is one folder that is the save; a **member bundle**
(`<ID6>.dolphin-gc.zip`, `<GAME ID>.ppsspp.zip`, `<SERIAL>.pcsx2.zip`) is the entries a layout selects inside
directories other games share (`domain/save_bundles.py`). Either way the save on disk is the truth, the zip is derived
from it and is what is hashed, tracked and uploaded, and a restore never touches an entry the layout does not own.

### Save-sync blocker

The reason a ROM that launches with a standalone emulator has no **standalone save set** — an unknown emulator, a save
folder the backend does not locate, a disc image with no readable code, PCSX2 on a single-file memory card
(`domain/save_sync_blockers.py`). A stable `reason` slug plus one sentence for the user. Its saves are not synced, and
the game page and the post-session notification say why; it is never a conflict and never stops a launch.

### Savestate / savestate backup / savestate slot

A **savestate** is an emulator snapshot of a running game (RetroArch's `.state` files), never an in-game save; it is
never called plain "state" in code. A **savestate backup** uploads a RetroArch savestate to RomM after the game exits
and the save sync is done (ADR-0031, `services/savestates/`): upload-only, opt-in, only savestates written since the
backup was turned on, and never restored automatically — "backup, not sync". A **savestate slot** is `auto`
(`.state.auto`) or `0`…`9` (`.state`, `.state1`…`.state9`), the keys RomM 5.5 snapshot banks use
(`domain/savestate_names.py`). A backup is filed on the server as `<booted stem> [<device short-id>].<slot suffix>`, one
row per device and slot.

### Console shelf / console page / most played

The **console shelf** is The Collector's row on Steam's Big Picture Home, under Recent games: one tile per console
(`platform_slug`) with at least one bound ROM, drawn as a stack of that console's media
(`src/patches/homeShelfPatch.tsx`, `services/console_shelf.py`). A **console page** is the route
`/the-collector/console/:slug` listing that console's games, "Continue" (its most recently played game) first. **Most
played** orders the shelf by recency-weighted play time: each game's play seconds halved for every 90 days since it was
last played (`domain/console_shelf.py`) — never lifetime play time.

### Achievement snapshot

The user's RetroAchievements progress per ROM as RomM last reported it (`ra_progression` from `GET /api/users/me`),
persisted in `rom_achievement_progress` (the `RomAchievementProgress` aggregate) and replaced as a whole from one
answer. A ROM with a set but no row has "no progress yet". It is only as fresh as RomM's own RetroAchievements sync.

### Achievement journal / goal / unlock timeline

The **achievement journal** is the user's own layer per RetroAchievements game (the `RaGameJournal` aggregate, keyed by
`roms.ra_id`, not by a ROM): free-text **notes** and **goals**. A **goal** is an achievement the user pinned; it is
**unlocked** (ticked off) once an unlock is seen in RomM's progress data or RetroAchievements' Web API, and an unlock
only moves forward (softcore may become hardcore, never back). The **unlock timeline** is the user's unlocks across games
read from RetroAchievements' Web API, which needs the **RetroAchievements Web API key** the user stores in The
Collector's settings — never an emulator's RetroAchievements login.

### Mod target / mod backup

A **mod target** is one place a game's mods go under the emulator it launches with (`domain/game_mods.py`
`ModTarget`): a **game** folder named by the game's own identifier (`Load\Textures\GALE01`), a **shared** folder every
game of the emulator reads (`Load\GraphicMods`), or a **soft patch** beside the ROM (`<ROM stem>.ips`). A target exists
only when the emulator's folder and the game's identifier were both read exactly; otherwise the game has "no known mod
folder". A **mod backup** is where the Mods panel moves what an install replaces or a removal takes away, and the ini
before a setting edit: `romm-mod-backups\<stamp>\<target>` inside the emulator's own data folder. Nothing in the
feature deletes.

### Fork build / release channel / kept build

A **fork build** is a Windows build of this fork, versioned `X.Y.Z-win.N`; `N` counts fork builds of one upstream
version and compares as a number. The **release channel** is the fork's `release` branch (`romm-dock.zip` +
`update.json`) that a fork build updates itself from (`domain/plugin_release.py`). The **kept build** is the snapshot
of the installed plugin folder taken before an update, which **Roll Back** reinstalls. Only a fork build on Windows uses
the channel; every other build is left to the Decky store.

### Install manifest / half-copied install / rescue mode

The **install manifest** is `install-manifest.json` in a release zip: the path, size and SHA-256 of every other file
(`domain/install_manifest.py`). A **half-copied install** is a plugin folder that does not match it — Decky Loader's
installer can stop part-way and leave old, new and missing files mixed. **Rescue mode** is `main.py` running only the
import-safe core (`core_bootstrap.py`: the install check and the update channel) because the rest of the plugin failed
to import; the QAM then offers **Reinstall**, which installs the published build without replacing the kept build.

### Baseline

The last-synced reference point recorded for a tracked save file — captured in a `FileSyncState` value object
(filename + hash + `tracked_save_id`). The newest-wins matrix diffs the current local and remote state against the
baseline to detect drift on the next sync. Adopting a baseline (`adopt_baseline(...)`) is how a file becomes tracked.

### Newest-wins matrix

The save-sync conflict-resolution model (`services/saves/sync_engine/`). For each tracked file it evaluates local vs
remote vs **baseline** and resolves to whichever side is newer, rather than blindly mirroring one direction. The
"matrix" is the per-file evaluation table that drives the actual upload / download / no-op dispatch for a ROM's sync
run.

### SyncRun

One library-sync operation modelled as a first-class aggregate (`domain/sync_run.py`, `sync_runs` table) — a `running` →
`completed` / `cancelled` / `errored` state machine carrying `started_at` / `finished_at`, the planned platform/ROM
counts, and the lists of platforms/collections actually completed. Replaces the scattered JSON scalars `last_sync`,
`sync_stats`, `last_synced_platforms`, `last_synced_collections`. One row per sync (inserted at apply-start, finalized
at the end). The "how many ROMs" figure is **not** stored on it — that is a live `len(registry)` count computed at read
time.

### Active session

One play session the frontend is currently tracking: `{appId, romId, startMs}` in `sessionManager`'s map, keyed by the
Steam app that opened it. There is one entry **per running app**, not one overall — two RomM games at once are two
active sessions, each finalizing on its own app's exit. An active session is opened by a game-start notification or by
reload-adoption, and its durable counterpart is the `last_session_start` marker on the ROM's `rom_playtime` row plus the
`romm-dock:active-session` breadcrumb that lets a reload adopt it. "Active" is about the frontend's tracking, not about
foreground/focus — a backgrounded game's session is still active.

### Unbind / stale / prune

Three deliberately-distinct ROM-removal notions (see [ADR-0007](docs/adr/0007-rom-retention-identity-anchor.md)):

- **Unbind** — drop a ROM's Steam-shortcut binding (`shortcut_app_id` → NULL, via `Rom.unbind_shortcut()`) while keeping
  its `roms` row and all per-ROM state (install, metadata, playtime, saves). What removing a shortcut does.
- **Stale** — a ROM still in local state but no longer returned by RomM on a sync. Triggers an **unbind**, never a
  delete: a stale signal may be a transient server blip or a reversible RomM change, and local playtime/saves must
  survive.
- **Prune** — an explicit, opt-in purge that `DELETE`s the `roms` row, cascading every per-ROM child away atomically.
  The **only** thing that deletes rows. **Clean Up Removed RomM Games** performs it only after fresh exact-ID 404s,
  explicit options, and any enabled recovery bundle have passed their final guards.

### Recovery bundle

A checksum-verified, atomically sealed pre-mutation snapshot created by explicit Prune. It records the affected local
aggregate state and selected/mandatory recoverable files for manual recovery; it is not a database export or an
automatic restore point. Finalization revalidates both the sealed bytes and their source state before deleting anything.

### Action token

A one-run, one-action lease for a frontend-owned Steam operation during Prune. The frontend must claim the exact token
before touching Steam and complete that same token afterward. Duplicate, stale, unknown, and late unclaimed tokens are
non-authoritative and cannot mutate Steam.

### Game-detail store

The single holder of the state one Steam game page shares across its surfaces (`src/utils/gameDetailStore.ts`): the
bound `rom_id`, install state, save-sync status, BIOS level and core selection, plus the reads that produce them. One
entry per appId — the first surface to subscribe opens it, the last to unsubscribe closes it, so a page that is off
screen holds nothing and listens to nothing. The `romm_data_changed` DOM bus keeps carrying the notifications and
carries no state: one handler per appId folds an event into the entry, and every subscriber renders from that one fold
rather than from its own copy. Overlapping reads for one appId share a single request, so a payload-less notification
costs one `get_save_status` round-trip however many surfaces are mounted. The foil to a surface's **own** state — the
play row's PLAYTIME / LAST PLAYED pair, which nothing else reads and which stays in the component.

### Collection kind (Standard / Smart / Virtual)

The axis on which a RomM collection is classified for syncing — the internal literal `standard` / `smart` / `virtual`
(the `enabled_collections` bucket keys, `WorkUnit.collection_kind`, and `CollectionSyncState.collection_kind`), matching
RomM's own UI vocabulary. **Standard** is a manually-created collection (RomM's ownership-carrying kind — its ROM
membership is hand-picked; the auto-managed favorites collection is a Standard one); **Smart** is a saved-search whose
membership resolves at query time; **Virtual** is an ownerless grouping RomM derives from IGDB metadata (franchise /
series). Only Standard and Smart are stampable for the incremental skip. Internal-name history: the first kind was
called `user` until #1539 renamed it `standard` (display "My" → "Standard").

### Collection owner-scope (Mine / All)

The ownership filter over the collection list on a shared RomM server — the `collection_owner_scope` setting valued
`all` (every collection the server lists, including other users' public ones) or `own` (only the signed-in user's own
collections). Orthogonal to the collection kind axis: it filters by owner (`is_own` / `user_id` vs `romm_user_id`), not
by kind, and virtual collections have no owner so they always survive. The stored value stays `own` / `all`; only the
QAM label is **Mine** / **All** (the value was left `own` to avoid a settings migration, #1539).

### Collection naming mode (merge / by_label)

How the Steam-collection **name** is formed when RomM collections share a display name across kinds — the
`collection_naming_mode` setting valued `merge` (default) or `by_label`. Under **`merge`**, same-named collections union
into one `RomM: [<name>] (<host>)` Steam collection (#1503). Under **`by_label`**, each name carries its **fine type
label** so distinct groupings stay separate: `RomM: [<name> (Franchise)]`, `RomM: [<name> (IGDB Collection)]`,
`RomM: [<name> (Smart)]`, `RomM: [<name> (Standard)]`. The label is the fine label, not the coarse kind — franchise and
IGDB-collection are both `kind="virtual"`, distinguished by `virtual_type` (see the **Collection kind** entry above).
Computed backend-side at the reporter's union key (`domain/collection_label.py`), so the wire payload stays name→appIds
and the frontend needs no change; the mode flip is applied by the ordinary complete-set reconcile on the next normal
sync (no Force Full Sync). Same-name-**within-one-label** still unions.

### Collection name style (Classic / Clean)

How the plugin's own Steam collections are **named** — the `collection_name_style` setting valued `classic` (default:
the names the plugin has always used, `RomM: <platform> (<host>)` / `RomM: [<name>] (<host>)`, plain `<platform>` /
`[<name>]` on Windows) or `clean` (the source's own name, no prefix or hostname). Orthogonal to the **Collection naming
mode**, which decides the source key a RomM collection is named from; the style decides what is wrapped around it.
Applies on the next sync by renaming owned collections.

### Owned Steam collection

A Steam collection the plugin made on this device, proven only by the **ownership record** — the `OwnedSteamCollection`
aggregate (`owned_steam_collections`), keyed by Steam's collection id, one per source (`family` `platform` / `romm` /
`installed` + case-folded source name; `installed` is the single **installed collection** of the shortcuts whose ROM is
on this device). Never inferred from a name: a collection without a record is the **user's**, and the plugin
never renames, refills or deletes it. When a source's wanted name is held by a user's collection, the plugin's
collection takes a suffixed name (`<name> (RomM)`) and the record keeps the user's name in `yielded_to`. Pre-record
collections are brought under the record once (**adoption**), by name plus proof (the `RomM:` prefix, or RomM-only
contents).
