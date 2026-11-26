"""Logic tests for FlightRecorder.lua outside the game (dev-only; does not ship).

Loads the addon into a mocked WoW environment on a real Lua 5.1 runtime (lupa)
and simulates taxi flights, reloads and slash commands.

Setup:  py -m venv .venv && .venv/Scripts/pip install lupa luaparser
Run:    .venv/Scripts/python tools/test_addon.py
"""
import os
import sys
import traceback

try:
    from lupa.lua51 import LuaRuntime
    LUA_NAME = "Lua 5.1 (lupa.lua51)"
except ImportError:  # fall back to whatever lupa bundles
    from lupa import LuaRuntime
    LUA_NAME = "lupa default runtime"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON = os.path.join(ROOT, "FlightRecorder.lua")

HARNESS = r"""
S = { now = 1000, taxi = false, speed = 0, y = 100, x = 200, log = {}, timers = {},
      cur = 1, routes = {}, noid = {}, hooks = {}, frames = {} }
local names = { "A", "B", "C", "D" }
local ids = { 10, 20, 30, 40 }

function newEnv(db)
  S.timers, S.frames, S.hooks = {}, {}, {}   -- a reload loses all of this
  local env = setmetatable({}, { __index = _G })
  env.FlightRecorderDB = db
  env.GetTime = function() return S.now end
  env.time = function() return math.floor(S.now) end
  env.print = function(...)
    local t = {}
    for i = 1, select("#", ...) do t[#t + 1] = tostring((select(i, ...))) end
    S.log[#S.log + 1] = table.concat(t, " ")
  end
  env.UnitOnTaxi = function() return S.taxi end
  env.UnitPosition = function() return S.y, S.x end
  env.GetUnitSpeed = function() return S.speed end
  env.UnitName = function() return "TestA" end
  env.UnitFactionGroup = function() return "Horde" end
  env.UnitClass = function() return "Warrior", "WARRIOR" end
  env.CreateFrame = function()
    local f = { scripts = {}, events = {} }
    f.RegisterEvent = function(self, ev) self.events[ev] = true end
    f.SetScript = function(self, n, fn) self.scripts[n] = fn end
    S.frames[#S.frames + 1] = f
    return f
  end
  env.C_Timer = {
    After = function(sec, fn) S.timers[#S.timers + 1] = { due = S.now + sec, fn = fn } end,
    NewTicker = function(iv, fn)
      local t = { due = S.now + iv, fn = fn, iv = iv }
      t.Cancel = function(self) self.dead = true end
      S.timers[#S.timers + 1] = t
      return t
    end,
  }
  env.hooksecurefunc = function(name, fn)
    S.hooks[name] = S.hooks[name] or {}
    table.insert(S.hooks[name], fn)
  end
  env.TakeTaxiNode = function(slot)
    for _, h in ipairs(S.hooks.TakeTaxiNode or {}) do h(slot) end
  end
  env.GetTaxiMapID = function() return 1414 end
  env.C_TaxiMap = { GetAllTaxiNodes = function()
    local l = {}
    for i = 1, 4 do
      local n = { slotIndex = i }
      if not S.noid[i] then n.nodeID = ids[i] end
      l[#l + 1] = n
    end
    return l
  end }
  env.NumTaxiNodes = function() return 4 end
  env.TaxiNodeGetType = function(i) return i == S.cur and "CURRENT" or "REACHABLE" end
  env.TaxiNodeName = function(i) return names[i] end
  env.GetNumRoutes = function(slot) return #S.routes[slot] - 1 end
  env.TaxiGetNodeSlot = function(slot, r, isFrom)
    local p = S.routes[slot]
    if isFrom then return p[r] else return p[r + 1] end
  end
  local maps = {
    [1413] = { name = "The Barrens", mapType = 3, parentMapID = 1414 },
    [1414] = { name = "Kalimdor", mapType = 2, parentMapID = 947 },
  }
  env.C_Map = {
    GetBestMapForUnit = function() return 1413 end,
    GetMapInfo = function(id) return maps[id] end,
    GetPlayerMapPosition = function()
      return { GetXY = function() return 0.5 + S.y / 100000, 0.5 end }
    end,
  }
  env.SlashCmdList = {}
  S.env = env
  local chunk = assert(loadfile(ADDON_PATH))
  setfenv(chunk, env)
  chunk()
  return env
end

function fire(ev, ...)
  for _, f in ipairs(S.frames) do
    if f.events[ev] and f.scripts.OnEvent then f.scripts.OnEvent(f, ev, ...) end
  end
end

local function runTimers()
  local fired = {}
  for _, t in ipairs(S.timers) do
    if not t.dead and t.due <= S.now then fired[#fired + 1] = t end
  end
  table.sort(fired, function(a, b) return a.due < b.due end)
  for _, t in ipairs(fired) do
    if not t.dead then
      if t.iv then t.due = t.due + t.iv else t.dead = true end
      t.fn()
    end
  end
  local keep = {}
  for _, t in ipairs(S.timers) do if not t.dead then keep[#keep + 1] = t end end
  S.timers = keep
end

function advance(sec)
  for _ = 1, math.floor(sec / 0.5 + 0.5) do
    S.now = S.now + 0.5
    if S.taxi then S.y = S.y + S.speed * 0.5 end
    runTimers()
  end
end

-- start a new session: fresh db (or the given one), addon loaded, ADDON_LOADED fired
function boot(db)
  newEnv(db or {})
  fire("ADDON_LOADED", "FlightRecorder")
  return S.env.FlightRecorderDB
end

function land()
  S.taxi, S.speed = false, 0
  fire("PLAYER_CONTROL_GAINED")
  advance(2)
end

-- pick dest from slot cur (optionally via a middle slot), take off, fly secs, land unless stay
function fly(cur, dest, via, secs, stay)
  S.cur = cur
  S.routes[dest] = via and { cur, via, dest } or { cur, dest }
  S.taxi, S.speed = false, 0
  S.env.TakeTaxiNode(dest)
  fire("PLAYER_CONTROL_LOST")
  S.taxi, S.speed = true, 30
  advance(secs)
  if not stay then land() end
end

function slash(msg) S.env.SlashCmdList["FLIGHTRECORDER"](msg) end

function logHas(sub)
  for _, l in ipairs(S.log) do if l:find(sub, 1, true) then return true end end
  return false
end

function clearLog() S.log = {} end
function logText() return table.concat(S.log, "\n") end
"""

lua = LuaRuntime(unpack_returned_tuples=True)
lua.globals().ADDON_PATH = ADDON
lua.execute(HARNESS)
G = lua.globals()


def flights(db):
    return [db.flights[i] for i in range(1, len(db.flights) + 1)]


def keys(db):
    return [f"{f.fromNode}>{f.toNode}:{'C' if f.complete else 'P'}:{f.note}" for f in flights(db)]


def check(cond, msg):
    if not cond:
        raise AssertionError(msg + "\n--- chat log ---\n" + G.logText())


FAILED = []


def test(fn):
    name = fn.__doc__ or fn.__name__
    G.clearLog()
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as e:  # noqa: BLE001
        FAILED.append(name)
        print(f"FAIL  {name}")
        if not isinstance(e, AssertionError):
            traceback.print_exc()
        else:
            print("      " + str(e).replace("\n", "\n      "))


SECS = 40  # flight length in seconds (80 samples at 0.5 s)


@test
def a_first_flight_recorded():
    """(a) first flight A->B is recorded"""
    db = G.boot()
    G.fly(1, 2, None, SECS)
    check(len(db.flights) == 1, f"expected 1 flight, got {keys(db)}")
    f = db.flights[1]
    check(f.complete is True and f.note == "landed", f"bad flight {keys(db)}")
    check(f.fromNode == 10 and f.toNode == 20, "node ids not stored")
    check(G.logHas("recording A -> B"), "no recording message")


@test
def b_repeat_skipped():
    """(b) second A->B is skipped silently, nothing new saved"""
    db = G.boot()
    G.fly(1, 2, None, SECS)
    G.clearLog()
    G.fly(1, 2, None, SECS)
    check(len(db.flights) == 1, f"expected 1 flight, got {keys(db)}")
    check(G.logText() == "", "a skipped repeat should print nothing")


@test
def c_reverse_direction_recorded():
    """(c) B->A is recorded (direction matters)"""
    db = G.boot()
    G.fly(1, 2, None, SECS)
    G.fly(2, 1, None, SECS)
    check(keys(db) == ["10>20:C:landed", "20>10:C:landed"], f"got {keys(db)}")


@test
def d_multistop_key_differs():
    """(d) multi-stop A->C via B has a different key from direct A->C"""
    db = G.boot()
    G.fly(1, 3, None, SECS)
    G.fly(1, 3, 2, SECS)
    check(len(db.flights) == 2, f"expected 2 flights, got {keys(db)}")
    via = db.flights[2]
    check(via.hops is not None and len(via.hops) == 2, "hops not stored on the multi-stop flight")
    check(db.flights[1].hops is None, "direct flight should have no hops")
    # the multi-stop route is now known too: repeating it is skipped
    G.clearLog()
    G.fly(1, 3, 2, SECS)
    check(len(db.flights) == 2 and G.logText() == "", "multi-stop repeat not skipped")
    # and the chain key is A>B>C (10>20>30), checked through a different chain A>D>C
    G.fly(1, 3, 4, SECS)
    check(len(db.flights) == 3, f"A>D>C should differ from A>B>C, got {len(db.flights)}")


@test
def e_repeats_off_keeps_best_only():
    """(e) /frec repeats off: repeat is recorded, only the best copy kept (count stays 1)"""
    db = G.boot()
    G.fly(1, 2, None, SECS)
    G.slash("repeats")
    check(db.settings.skipRepeats is False, "toggle did not turn skipRepeats off")
    check(G.logHas("skip repeats off"), "no toggle message")
    G.clearLog()
    G.fly(1, 2, None, SECS)
    check(G.logHas("recording A -> B"), "repeat was not recorded with repeats off")
    check(len(db.flights) == 1, f"expected 1 flight after keep-best, got {keys(db)}")
    check(G.logHas("replaced an older copy"), "save message does not mention replacing")
    G.slash("repeats")
    check(db.settings.skipRepeats is True, "toggle did not turn skipRepeats back on")
    G.slash("status")
    check(G.logHas("skipRepeats=true"), "status does not show skipRepeats")


@test
def e2_keep_best_prefers_more_points():
    """(e2) keep-best: a shorter new copy does not replace a longer complete one"""
    db = G.boot()
    G.fly(1, 2, None, SECS)
    G.slash("repeats")  # off
    G.fly(1, 2, None, 20)
    check(len(db.flights) == 1 and len(db.flights[1].points) > 60,
          f"longer copy should survive, got {len(db.flights[1].points)} points")
    check(G.logHas("kept the better existing copy"), "message missing")


@test
def f_incomplete_copy_replaced():
    """(f) an incomplete saved copy does not block; the new complete flight replaces it"""
    db = G.boot()
    lua.execute("""
      local db = S.env.FlightRecorderDB
      db.flights[1] = { from = "A", to = "D", fromNode = 10, toNode = 40, complete = false,
                        note = "timeout", started = 500, zones = {},
                        points = { { 0, 1, 1 }, { 1, 2, 2 }, { 2, 3, 3 } } }
    """)
    G.fly(1, 4, None, SECS)
    check(G.logHas("recording A -> D"), "incomplete copy blocked recording")
    check(len(db.flights) == 1, "should not have skipped")
    check(keys(db) == ["10>40:C:landed"], f"got {keys(db)}")


@test
def g_nil_node_ids_never_skipped():
    """(g) a flight with nil node IDs is never skipped"""
    db = G.boot()
    lua.execute("S.noid[2] = true")
    G.fly(1, 2, None, SECS)
    G.fly(1, 2, None, SECS)
    lua.execute("S.noid[2] = nil")
    check(len(db.flights) == 2, f"expected both recorded, got {keys(db)}")
    check(db.flights[1].toNode is None, "toNode should be nil")
    check(G.logHas("recording A -> B"), "skipped a flight with unknown node ids")


@test
def h_reload_during_skipped_flight():
    """(h) reload during a skipped flight does not start a joined recording"""
    db = G.boot()
    G.fly(1, 2, None, SECS)
    G.clearLog()
    G.fly(1, 2, None, 10, True)  # skipped, still on the taxi
    check(db.skipping is None and len(db.flights) == 1 and G.logText() == "",
          "setup: flight was not skipped")
    G.fire("PLAYER_LOGOUT")
    check(db.skipping is not None and db.skipping.savedAt is not None, "db.skipping not persisted")
    check(len(db.flights) == 1, f"logout added a flight: {keys(db)}")
    G.advance(3)
    G.clearLog()
    db = G.boot(db)  # same table, fresh addon load (the /reload)
    G.fire("PLAYER_ENTERING_WORLD")
    G.advance(5)     # covers the 2 s second check
    check(not G.logHas("recording"), "a recording started after the reload")
    check(db.skipping is None, "db.skipping was not cleared")
    G.advance(10)
    G.land()
    check(len(db.flights) == 1, f"a joined flight was saved: {keys(db)}")


@test
def h2_reload_twice_still_skipped():
    """(h2) a second reload during the same skipped flight is also guarded"""
    db = G.boot()
    G.fly(1, 2, None, SECS)
    G.fly(1, 2, None, 10, True)
    G.fire("PLAYER_LOGOUT")
    G.advance(3)
    db = G.boot(db)
    G.fire("PLAYER_ENTERING_WORLD")
    G.advance(5)
    G.fire("PLAYER_LOGOUT")
    check(db.skipping is not None, "marker not re-armed and persisted on the second logout")
    G.advance(3)
    G.clearLog()
    db = G.boot(db)
    G.fire("PLAYER_ENTERING_WORLD")
    G.advance(5)
    G.land()
    check(not G.logHas("recording") and len(db.flights) == 1, f"got {keys(db)}")


@test
def h3_control_joined_without_marker():
    """(h3) control: without a skip marker a reload on a taxi starts a joined recording"""
    db = G.boot()
    lua.execute("S.taxi, S.speed = true, 30")
    G.fire("PLAYER_ENTERING_WORLD")
    G.advance(5)
    check(G.logHas("recording"), "joined recording did not start (test setup is wrong)")
    G.advance(20)
    G.land()
    check(len(db.flights) == 1 and db.flights[1].note == "joined mid-flight", f"got {keys(db)}")


@test
def h4_stale_skip_marker_ignored():
    """(h4) a skip marker older than 120 s does not suppress a joined recording"""
    db = G.boot()
    G.fly(1, 2, None, SECS)
    G.fly(1, 2, None, 10, True)
    G.fire("PLAYER_LOGOUT")
    G.advance(200)
    db = G.boot(db)
    G.fire("PLAYER_ENTERING_WORLD")
    G.advance(5)
    check(G.logHas("recording"), "stale marker suppressed the recording")
    check(db.skipping is None, "stale marker not cleared")


@test
def i_logout_resume_still_works():
    """(i) logout -> resume still works for a recorded flight"""
    db = G.boot()
    G.fly(1, 2, None, 20, True)  # recording in progress
    G.fire("PLAYER_LOGOUT")
    check(len(db.flights) == 1 and db.flights[1].note == "logout", f"got {keys(db)}")
    check(db.skipping is None, "no skip marker expected for a recorded flight")
    G.advance(3)
    G.clearLog()
    db = G.boot(db)
    G.fire("PLAYER_ENTERING_WORLD")
    G.advance(1)
    check(len(db.flights) == 0, "logout entry should be taken back while resuming")
    check(not G.logHas("recording"), "resume should not announce a recording")
    G.advance(20)
    G.land()
    check(G.logHas("saved A -> B"), "resumed flight did not print saved")
    check(keys(db) == ["10>20:C:resumed"], f"got {keys(db)}")


@test
def j_logout_entry_survives_keep_best():
    """(j) a logout entry for a route is not removed by keep-best before the resume"""
    db = G.boot()
    G.fly(1, 2, None, SECS)            # complete copy exists
    G.slash("repeats")                 # off, so the repeat records
    G.fly(1, 2, None, 20, True)
    G.fire("PLAYER_LOGOUT")
    check(len(db.flights) == 2 and db.flights[2].note == "logout", f"got {keys(db)}")
    G.advance(3)
    db = G.boot(db)
    G.fire("PLAYER_ENTERING_WORLD")
    G.advance(1)
    check(len(db.flights) == 1, "logout entry was not resumed")
    G.advance(30)
    G.land()
    check(len(db.flights) == 1 and db.flights[1].complete is True, f"got {keys(db)}")


# ---- cleanup of old duplicates on load (pruneRepeats) ----

def preload(*fl):
    """boot with a preloaded FlightRecorderDB holding the given flight dicts (lua source strings)."""
    lua.execute("PRE = { flights = { " + ", ".join(fl) + " } }")
    return G.boot(G.PRE)


def fl(fn, tn, complete=True, pts=3, started=100, note=None, saved=None, hops=None, tag=None):
    parts = [f"complete = {str(complete).lower()}", f"started = {started}", "zones = {}",
             "points = { " + ", ".join(f"{{ {i}, {i}, {i} }}" for i in range(pts)) + " }"]
    if fn is not None:
        parts += [f"fromNode = {fn}", f"toNode = {tn}"]
    if note:
        parts.append(f'note = "{note}"')
    if saved is not None:
        parts.append(f"savedAt = {saved}")
    if hops:
        parts.append("hops = { " + ", ".join(
            "{ 'x', 'y', %d, %d }" % h for h in hops) + " }")
    if tag:
        parts.append(f'tag = "{tag}"')
    return "{ " + ", ".join(parts) + " }"


def tags(db):
    return [f.tag for f in flights(db)]


@test
def k_prune_duplicates_on_load():
    """(k) load removes old duplicates: right copy kept, order stable, nil-key untouched, count reported"""
    db = preload(
        fl(10, 20, False, 9, 100, tag="r1-partial"),      # 0
        fl(10, 30, True, 5, 100, tag="r2-few"),           # 1
        fl(10, 20, True, 4, 100, tag="r1-complete"),      # 2  complete beats partial (more points)
        fl(None, None, True, 3, 100, tag="nokey1"),       # 3
        fl(40, 10, True, 3, 100, tag="unique"),           # 4
        fl(10, 30, True, 8, 100, tag="r2-more"),          # 5  more points beats fewer
        fl(None, None, True, 3, 100, tag="nokey2"),       # 6
        fl(10, 20, True, 4, 300, tag="r1-newest"),        # 7  tie on points -> newest
        fl(10, 30, True, 8, 50, tag="r2-older-tie"),      # 8
    )
    check(tags(db) == ["nokey1", "unique", "r2-more", "nokey2", "r1-newest"],
          f"got {tags(db)}")
    check(G.logText() == "", "load-time cleanup should be silent")


@test
def l_prune_hops_keyed_and_directional():
    """(l) multi-stop flights are keyed by hop chain; A>B>C and C>B>A both survive, duplicates go"""
    db = preload(
        fl(None, None, True, 3, 100, hops=[(10, 20), (20, 30)], tag="abc-old"),
        fl(None, None, True, 3, 100, hops=[(30, 20), (20, 10)], tag="cba"),
        fl(None, None, True, 3, 200, hops=[(10, 20), (20, 30)], tag="abc-new"),
        fl(10, 30, True, 3, 100, tag="direct"),            # different key from the chain
    )
    check(tags(db) == ["cba", "abc-new", "direct"], f"got {tags(db)}")
    check(not G.logHas("removed"), "load-time cleanup should be silent")


@test
def m_prune_nothing_to_do():
    """(m) no duplicates: list unchanged and no chat message"""
    db = preload(fl(10, 20, tag="a"), fl(20, 10, tag="b"), fl(None, None, tag="c"))
    check(tags(db) == ["a", "b", "c"], f"got {tags(db)}")
    check(not G.logHas("removed"), "printed a message with nothing removed")


@test
def n_prune_keeps_resumable_logout_entry():
    """(n) a fresh logout entry stays last next to a complete copy and still resumes"""
    db = preload(
        fl(10, 20, True, 5, 100, tag="complete"),
        fl(10, 20, False, 3, 990, note="logout", saved=int(G.S.now), tag="resume"),
    )
    check(tags(db) == ["complete", "resume"], f"got {tags(db)}")
    check(not G.logHas("removed"), "should not have removed anything")
    lua.execute("S.taxi, S.speed = true, 30")
    G.fire("PLAYER_ENTERING_WORLD")
    G.advance(1)
    check(not G.logHas("recording"), "resume should not announce a recording")
    check(tags(db) == ["complete"], f"logout entry not taken back for resume: {tags(db)}")
    G.advance(20)
    G.land()
    check(len(db.flights) == 1 and db.flights[1].complete is True, f"got {keys(db)}")


@test
def o_prune_stale_logout_entry_removed():
    """(o) a stale logout entry (10 minutes old) is an ordinary candidate and is removed"""
    db = preload(
        fl(10, 20, True, 5, 100, tag="complete"),
        fl(10, 20, False, 3, 400, note="logout", saved=int(G.S.now) - 600, tag="stale"),
    )
    check(tags(db) == ["complete"], f"got {tags(db)}")
    check(not G.logHas("removed"), "load-time cleanup should be silent")

@test
def p_new_flight_messages():
    """(p) a new flight prints exactly one recording line at takeoff, then saved at landing"""
    G.boot()
    G.fly(1, 2, None, SECS, True)
    check(len(G.S.log) == 1 and G.S.log[1].endswith("recording A -> B"),
          "expected exactly one recording line")
    G.land()
    check(len(G.S.log) == 2 and "saved A -> B" in G.S.log[2], "expected a saved line at landing")


@test
def q_phantom_recording_silent():
    """(q) on a taxi but never at taxi speed for 10 s: discarded with no chat output"""
    db = G.boot()
    G.S.cur = 1
    lua.execute("S.routes[2] = { 1, 2 }; S.taxi, S.speed = false, 0")
    G.S.env.TakeTaxiNode(2)
    G.fire("PLAYER_CONTROL_LOST")
    lua.execute("S.taxi, S.speed = true, 0")
    G.advance(1)
    check(len(G.S.log) == 1 and "recording" in G.S.log[1], "setup: recording did not start")
    G.advance(15)
    check(len(db.flights) == 0, f"phantom was saved: {keys(db)}")
    check(len(G.S.log) == 1, "discard should print nothing more")


print()
print(f"Lua runtime: {lua.eval('_VERSION')} via {LUA_NAME}")
if FAILED:
    print(f"{len(FAILED)} FAILED: " + "; ".join(FAILED))
    sys.exit(1)
print("all tests passed")
