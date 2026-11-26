## 1.1.0 - 2026-11-25

- Skips routes you already have: a repeat of a saved, complete route (same flight masters, same direction) is not recorded
- `/frec repeats` toggles this (default on); `status` shows it
- When a repeat is recorded anyway, or a complete flight replaces a partial one, only the best copy of that route is kept
- A /reload during a skipped flight no longer starts a "joined mid-flight" recording
- On load, repeat flights already saved (from before this version) are removed, keeping the best copy of each route; a flight waiting to resume after a /reload is left alone

## 1.0.0 - 2026-11-24

- Records every taxi flight: position every 0.5 s, world + continent-map coordinates, hops, zones
- Landing detection by UnitOnTaxi or measured speed
- Resumes after a /reload mid-flight
- Discards recordings that never reach taxi speed
- /frec commands
