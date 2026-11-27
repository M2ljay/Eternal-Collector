# ROM Game Page (Core design)

A ROM's Steam game page is Steam's own app-details page with The Collector's panel in place of Steam's overview panel.
User-facing behaviour is in [Managing Games](../user-guide/managing-games.md#the-game-detail-panel); this page is how
the page is put together and which rules it keeps.

## Structure

`patches/gameDetailPatch.tsx` finds Steam's `InnerContainer` and replaces the native `AppDetailsOverviewPanel` with
`rommPageWrapper`: a `div` carrying the native panel's class (so it takes part in Steam's flex layout and scrolling)
that holds `RomMPlaySection` and `RomMGameInfoPanel`. Steam keeps drawing the header (hero art and logo) above it.

| Part           | Module                                                  | Owns                                                                             |
| -------------- | ------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Header         | `components/RomPageHeader.tsx`                          | Name, platform chip (family tone), The Collector chip, last-played/playtime line |
| Play bar       | `components/RomMPlaySection.tsx`, `CustomPlayButton`    | Play/Download states, pickers, status line, Options/emulator/Mods buttons        |
| Tabs           | `components/PanelTabBar.tsx`                            | Overview, Achievements, extension tabs, Saves, Media, Details, BIOS              |
| Overview cards | `components/RomOverviewCards.tsx`, `GamePageExtensions` | RetroAchievements and Save sync cards, then registered cards, in one grid        |
| Panes          | `components/panelTabContent.tsx`                        | Overview summary, Details (`GameInfoTab`), Media (`RomMediaTab`), Saves          |
| Core styles    | `utils/corePageStyles.ts`                               | The one stylesheet for the Core page                                             |
| Family tones   | `theme/coreTokens.ts` (`consoleFamily`, `familyTones`)  | RomM platform slug to PlayStation / Nintendo / Sega / Xbox / retro               |

The header and the play-bar status line render only under the Windows look (`nativeLook()`), where the wrapper is also
the Core page (`.romm-core-page`). The tabs, cards and panes are the same on every platform; the Steam Deck keeps its
older play row.

## The Core page's styles

`ensureCorePageStyles()` injects one stylesheet into Big Picture's document the first time a ROM page renders. Every
rule is scoped under `.romm-core-page`; the two that reach outside it go through `:has(> .romm-core-page)`, so a Steam
game page is never touched:

- `InnerContainer` is painted black, and the header's art (`appDetailsHeaderClasses.ImgContainer`) gets a mask that
  fades it to transparent over the black. The logo is not masked.
- The play bar keeps Steam's play-section classes (`basicAppDetailsSectionStylerClasses.PlaySection`, `ActionRow`,
  `AppButtons`, `appActionButtonClasses.PlayButtonContainer`), so a rule Core UI writes for Steam's play bar in its
  game-page phase applies to both kinds of page. On top: glass (`rgba(26,29,33,.62)` with an 18px blur, float radius),
  crimson Play with a white 3px focus ring, square gunmetal menu buttons with a crimson outline on focus.
- Tabs carry one crimson underline (an inset shadow, so it never shifts the row); a focused tab is gunmetal.
- Cards are gunmetal with `var(--core-radius-float, 10px)`; focus is gunmetal raised plus a crimson outline, no glow.

A class map Steam renames leaves its rule out; the rest still applies.

### Stars

Core UI's design rule is that a black surface gets the Core Starfield. Core UI attaches its animated canvas only to the
surfaces in its own host list, which does not include this page yet. Until it does, the wrapper's first child
(`.romm-core-stars`) paints a still, seeded field (`starfieldSvg`, no star above 24% opacity, Core UI's ceiling) and
shows only under `html[data-core-ui]`. Without Core UI the page is plain black. When Core UI takes the page as a host it
sets `data-core-ui-host="1"` on it, and the still field steps aside.

## Rules kept

- **ROM identity.** The header renders from the play section's `useGameDetail` state; the Overview cards render from the
  panel's state (`raId`, `achievements`, `saveSyncEnabled`, `saveStatus`, `conflicts`) and read nothing themselves.
  `achievements` is written only alongside `raId`, at the two identity writes (`loadData` and the version switch), so a
  switch re-renders the cards with the switched-to version's answers. Card and tab presses only set `activeTab`; no
  write crosses an `await`, so the `writerForRom` / `RomBinding` rule has no new site.
- **Every action stays reachable.** The Options menu holds what the separate RomM Actions and Steam Properties buttons
  held; the cover moved from Details to Media, the description from Details to the Overview; BIOS keeps its own tab.
- **Controller.** The play bar, tab row, card grid and panes are `Focusable` rows and columns; cards are
  `DialogButton`s, so A opens their tab.
