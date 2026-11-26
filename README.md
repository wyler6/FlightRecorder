# Flight Recorder

Records the exact path of every flight path (taxi) you take as a list of position samples. The addon itself has no window; the routes are drawn by the flight map page in `map/` (see **Flight map** below).
Recordings that never reach taxi speed within 10 s are discarded (not saved).
Routes you already have are skipped: a taxi route always follows the same path, so a repeat of a saved, complete route (same flight masters, same direction) is not recorded again. Use `/frec repeats` to turn this off. On load the addon also removes repeat flights already saved, keeping the best copy of each route.

**Install note:** a new addon needs a full game restart (not /reload) the first time.

**Data location:** written on logout or /reload to `WTF\Account\<account>\SavedVariables\FlightRecorder.lua` (variable `FlightRecorderDB`).

## Commands (`/frec` or `/flightrec`)
- `help` - list commands
- `status` - settings, current recording, flights saved
- `list [n]` - last n flights (default 10), newest last
- `delete <index>` - delete one flight
- `clear confirm` - delete all flights
- `on` / `off` - enable or disable recording
- `quiet` - toggle chat messages
- `repeats` - toggle skipping routes already saved (default on)
- `interval <seconds>` - sample interval, 0.2 to 5 (default 0.5)

## Data format
`FlightRecorderDB = { version = 1, settings = { enabled, interval, quiet, skipRepeats }, flights = { ... } }`

Each flight:
- `char`, `faction`, `class` - player name (no realm), faction group, class token
- `from`, `to` - node names (nil if unknown); `fromNode`, `toNode` - taxi node IDs
- `hops` - multi-stop routes only: list of `{fromName, toName, fromNode, toNode}`
- `taxiMap` - taxi map ID; `continent` - continent uiMapID
- `started` - `time()` at takeoff; `duration` - seconds; `distance` - world yards (2D, integer)
- `complete` - true if the landing was seen; `note` - `landed`, `resumed`, `joined mid-flight`, `logout` or `timeout`; `savedAt` - only on `logout` entries
- `zones` - `{ {t, uiMapID, zoneName}, ... }`, added when the best map changes
- `points` - `{ {t, y, x, cx, cy}, ... }`
  - `t` - seconds since takeoff (1 decimal)
  - `y, x` - `UnitPosition` world coordinates in Blizzard's (posY, posX) order, 1 decimal
  - `cx, cy` - position on the continent map, 0 to 1, 5 decimals (may be missing)

## Flight map
`map\flight_map.html` is a companion web page that draws every recorded flight over the continent maps (Kalimdor and Eastern Kingdoms), so you can see the exact routes taken.

To update it, double-click `map\Update Flight Map.bat` after a /reload or logout in WoW (that is when the game writes the SavedVariables file). The script converts the data, publishes it to the online map (it commits and pushes `map/flights-data.js` to GitHub), and opens the page.

An online copy runs on GitHub Pages: https://wyler6.github.io/FlightRecorder/

Map art: the Forever continent tiles come from the OpenMap addon, https://github.com/openmap-world/openmap. The art is Blizzard's; see OpenMap's `OpenMap/Media/Textures/Forever/NOTICE.md`.

## Development
- `pwsh tools/deploy.ps1` copies the addon into the game. A full game restart is only needed the first time a new addon appears; after that, /reload.
- Never edit inside the AddOns folder. The next deploy overwrites it; make changes in this repo.
