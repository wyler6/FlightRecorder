# FlightRecorder

A World of Warcraft **Forever** addon that records the exact path of every flight-path (taxi) trip, plus a web page that draws the recorded routes on Forever's continent maps. Built 2026-11-24 with Claude Code. The user plays characters of both factions on one account. **The repo is public: never write character names into it** (files, data or commit messages). Claude's local memory has them.

## Layout

The repo root is the addon folder, the same pattern as the user's `E:\Projects\HowFarHaveIBeen`.

| Path | What it is |
|---|---|
| `FlightRecorder.toc`, `FlightRecorder.lua` | The addon (interface 16001, no libraries, one file of Lua 5.1) |
| `README.md`, `CHANGELOG.md` | User docs; both ship with the addon |
| `tools/deploy.ps1` | Copies the addon into the game's AddOns folder |
| `tools/flightmap_export.py` | Reads the SavedVariables and writes `map/flights.json` + `map/flights-data.js` (stdlib only) |
| `map/flight_map.html` | The route map page (works from disk and as a claude.ai Artifact) |
| `map/maps/kalimdor.jpg`, `map/maps/eastern_kingdoms.jpg` | Forever continent art, 2004x1336 |
| `map/Update Flight Map.bat` | What the user double-clicks: runs the exporter, commits and pushes only `map/flights-data.js` (the online map), then opens the local page |
| `.pkgmeta` | Packaging config in case it is ever published to CurseForge; map/ and tools/ don't ship |
| `index.html`, `.nojekyll` | GitHub Pages only: the root page forwards to the map; `.nojekyll` serves files as-is. Neither ships |

`map/flights.json` and `map/flights-data.js` are both generated. `flights.json` is git-ignored; `flights-data.js` is **committed** so the GitHub Pages map shows the flights. The exporter drops `char` and `class`, so the exported data has **no character names or classes**, only `faction`.

## Game environment

- Install: `F:\World of Warcraft\_forever_`. Client 1.60.x, a Classic Era based client, so use the Classic Era API. Addon interface number **16001**.
- AddOns: `F:\World of Warcraft\_forever_\Interface\AddOns\FlightRecorder`. This is a **deployed copy**: never edit it, run `pwsh tools/deploy.ps1` instead.
- Saved data: `F:\World of Warcraft\_forever_\WTF\Account\WYLER6\SavedVariables\FlightRecorder.lua` (account-wide `FlightRecorderDB`).
  - WoW writes it only on `/reload` or logout.
  - Editing it only sticks with WoW fully closed. The user prefers not to close WoW, so don't plan on editing it.
- A brand-new addon folder needs one full game restart. After that, `/reload` picks up changes.
- Never key anything by realm. The character name alone is the key.

## Data format (`FlightRecorderDB`)

`{ version = 1, settings = { enabled, interval = 0.5, quiet }, flights = { ... } }`

Each flight has these fields:
- `char`, `faction`, `class`
- `from`, `to`: node names like "Ratchet, The Barrens"
- `fromNode`, `toNode`: taxi node IDs
- `hops`: multi-stop routes only, `{ {fromName, toName, fromNode, toNode}, ... }` as positional arrays
- `taxiMap`, `continent`: uiMapID, 1414 = Kalimdor, 1415 = Eastern Kingdoms
- `started`: unix time
- `duration`: seconds
- `distance`: world yards, 2D
- `complete`: bool
- `note`: `landed`, `resumed`, `joined mid-flight`, `logout` or `timeout`
- `savedAt`: only on `logout` entries
- `zones`: `{ {t, uiMapID, zoneName}, ... }`
- `points`: `{ {t, y, x, cx, cy}, ... }`
  - `t`: seconds since takeoff
  - `y, x`: `UnitPosition` world coordinates in Blizzard's (posY, posX) order
  - `cx, cy`: 0–1 coordinates on the continent map; may be missing

## How the addon works, and why

- **Takeoff.**
  - `hooksecurefunc("TakeTaxiNode")` captures from/to names, node IDs and hops while the taxi map is open. Node IDs come from `C_TaxiMap.GetAllTaxiNodes(GetTaxiMapID())` via slotIndex → nodeID; hops come from `GetNumRoutes` / `TaxiGetNodeSlot`.
  - Recording starts when `UnitOnTaxi("player")` is true **and** the pick is at most 15 s old. It is checked on `PLAYER_CONTROL_LOST` and 0.5/1.5/3 s after the pick.
- **Sampling.** Every 0.5 s. A sample is skipped if the player moved under 0.5 yd. Continent coordinates come from walking `C_Map.GetMapInfo` parents up to mapType Continent (2), then calling `C_Map.GetPlayerMapPosition(continentID)`.
- **Landing.** This is the tricky part. On this client **`UnitOnTaxi` can stay true after landing** (first seen in the OneForAll addon's `Flights.lua`).
  - Landing is detected when `UnitOnTaxi` is false **or** the speed is below 20 yd/s for 3 s after it was at least 20 once. Taxis fly about 30 yd/s.
  - Speed is **measured from `UnitPosition` deltas** between ticks, with `GetUnitSpeed` only as a fallback. Either source can mark the flight as "fast".
- **Phantom guard.** If taxi speed is never reached within 10 s, the recording is discarded. This covers a stuck `UnitOnTaxi`, clicking a flight you can't afford, or a loading screen.
- **/reload mid-flight.**
  - `PLAYER_LOGOUT` saves the partial flight with `note = "logout"` and `savedAt`.
  - `PLAYER_ENTERING_WORLD` (immediately and again 2 s later) resumes it if `UnitOnTaxi` and `savedAt` was at most 120 s ago.
  - A resumed recording that never reaches speed is put back exactly as it was saved.
- **Safety.** There is a 30-minute timeout. All handlers run through one pcall wrapper that prints the first error once.
- **Slash commands:** `/frec` and `/flightrec`, with `status`, `list [n]`, `delete <i>`, `clear confirm`, `on`/`off`, `quiet`, `interval <s>`.
- **First real test, 2026-11-24:** a Horde character, Ratchet → Crossroads → Freewind Post, 4:13, 7,616 yd, 505 points, no gap over 0.6 s, correct hops and zones.

## The map page

- **File format.** It's a single file with **no `<!doctype>`, `<html>`, `<head>` or `<body>` on purpose**. The claude.ai Artifact publisher wraps it, and browsers are fine with it locally. It starts with `<title>`, then `<meta name="claude:viewport-fit-sides" content="cover">`, then `<style>`.
- **Data loading.** `flights-data.js` sets `window.FLIGHT_DATA`. That makes it work from `file://`, where `fetch` is blocked. Otherwise it fetches `flights.json`.
- **No header, no file loading.** At the user's request the title, stats line and the "Load FlightRecorder.lua" loader were removed; the page starts with the continent, faction and zoom bar, and only shows the exported data. There's no drag-and-drop, no `parseLua` and no localStorage; at start-up it removes the old `flightmap.loaded.v1` key once. If the data can't load, the map note says so.
- **Drawing.**
  - Points are `[t, cx, cy]`, and pixel = (cx × naturalWidth, cy × naturalHeight).
  - **Faction only, no characters.** Routes are colored by faction: Alliance `#1b55a0`, Horde `#b3231a`, unknown faction ("Other") `#3a6a2c`. The legend has one toggle per faction, and list rows show the faction. No character name or class appears anywhere on the page or in the published data (the exporter drops `char` and `class`). The user asked for this; don't bring back per-character colors, filters or names.
  - Start (circle) and end (diamond) markers, labels and direction arrows keep a constant screen size through the `scaled` list and `applyScaled()`.
  - `arrowSpots()` places about one arrow per 80 map px, with the heading smoothed over 5% of the path.
  - The hovered or pinned route gets marching dashes, which are turned off under `prefers-reduced-motion`.
- **Map art.** Built from the OpenMap addon's Forever tiles: https://github.com/openmap-world/openmap, `OpenMap/Media/Textures/Forever/MapArt/<1414|1415>_<1..12>.tga`.
  - The tiles form a 4x3 grid of 256 px (1024x768). Crop the top-left 1002x668 (the uiMap canvas), then Lanczos 2x to 2004x1336, JPEG quality 88.
  - Alignment was verified by drawing real flights on both maps: Ratchet → Freewind Post on Kalimdor, Tarren Mill → Undercity on Eastern Kingdoms.
  - The art is Blizzard's, not covered by OpenMap's MIT license; see OpenMap's `OpenMap/Media/Textures/Forever/NOTICE.md`. It has no rule against reposting, and OpenMap hosts the same tiles publicly.
- **GitHub.** https://github.com/wyler6/FlightRecorder (public since 2026-11-24).
  - GitHub Pages serves `main` from the root: https://wyler6.github.io/FlightRecorder/ forwards to `map/flight_map.html`.
  - `Update Flight Map.bat` updates the online flights by itself: after the export it commits only `map/flights-data.js` ("Update flight data", no Co-Authored-By) and pushes. If nothing changed it skips the commit; if git is missing it skips publishing; on a commit or push failure it pauses with a message. It always opens the local page at the end. To test it without opening the browser, run a copy without the last `start` line.
  - Never commit anything containing the user's Windows user folder path (it is their real name). Use `%LOCALAPPDATA%` or the `py` launcher instead.
  - Never commit character names either.
  - History was rewritten twice on 2026-11-24 to remove both, each time followed by deleting and recreating the GitHub repo, since a force-push leaves old commits reachable from the Activity page.
- **Published claude.ai copy.** https://claude.ai/artifact/H7BwKaVhg4FupWs4hc3E34 (private).
  - To update it, publish `map/flight_map.html` with `url` set to that link and `files` set to `flights.json` and `flights-data.js`; the maps are already uploaded.
  - In the old session a Read permission rule blocked publishing `flights.json`. If that happens again, ask the user.
  - The user mostly uses the **local** page, so the online copy is secondary.
  - Artifact rules to keep:
    - fonts only from Google Fonts
    - no other external resources
    - colors as tokens with light and dark blocks
    - side gutter `max(16px, env(safe-area-inset-*))`
    - no alert/confirm/prompt or download links

## Checking work without the game or a browser

- **Lua.** No Lua interpreter is installed. To syntax-check, make a venv (`.venv/`, git-ignored), install `luaparser`, and run `luaparser.ast.parse` on the file. Logic can only be tested in game, so the user tests on their next flight.
- **JavaScript.** Deno is at `%LOCALAPPDATA%\Microsoft\WinGet\Packages\DenoLand.Deno_Microsoft.Winget.Source_8wekyb3d8bbwe\deno.exe`.
  - Extract the main inline `<script>` and run `deno check --no-config`.
  - For logic, eval `flights-data.js` with `globalThis.window = globalThis` and call the pure functions (`normFlight`, `arrowSpots`).
- **Python.** `%LOCALAPPDATA%\Programs\Python\Python310\python.exe`; the `py` launcher also works.
- **Map alignment.** Draw a flight's cx/cy onto the jpg with Pillow, in the venv, and look at it with the Read tool.

## User preferences

- **Never open the user's browser.** No Chrome/browser tools, and no `start` on an .html, unless they ask. Tell subagents the same.
- The user's global CLAUDE.md (architect and delegate) applies here too.
- Keep answers short and plain. Say what was verified and what wasn't.
- **American spelling everywhere**: replies, docs, comments, UI text, commit messages (color, gray, license, -ize).

## Ideas not done yet

- Draw the recorded routes on the **in-game** world map as well (it was discussed; the user chose the web page first).
- Get **every** route exactly from the client's `TaxiPathNode` table. OneForAll's `Data/FlightPaths.lua` was generated from it, but that extraction tool isn't on this PC.
- Arrows follow the recorded path, so take-off hooks and landing circles can still tilt one.
- Release on CurseForge like HowFarHaveIBeen; `.pkgmeta` is ready and the GitHub repo exists; it would still need a LICENSE.

## Related code to read (read-only)

- `F:\World of Warcraft\_forever_\Interface\AddOns\OneForAll\Flights.lua`: flight times and the `UnitOnTaxi` landing workaround.
- `E:\Projects\HowFarHaveIBeen\Core.lua`: position reading (`UnitPosition`, C_Map fallback). `tools\deploy.ps1` there is the original deploy script.
