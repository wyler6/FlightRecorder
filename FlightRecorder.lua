-- FlightRecorder: records the exact path of every taxi flight (recording only, no UI).
local PREFIX = "|cff33ccffFlightRecorder|r:"
local DEFAULTS = { enabled = true, interval = 0.5, quiet = false }
local SPEED_LIMIT = 20      -- yd/s; taxis fly about 30, running/riding is below 20
local SLOW_SECS = 3         -- seconds below the limit (after being fast) that count as landed
local MAX_SECS = 1800       -- safety timeout
local MIN_MOVE = 0.5        -- yd between kept samples
local PICK_MAX_AGE = 15     -- seconds before a pick is stale

local db
local pick          -- the last picked flight (from TakeTaxiNode)
local rec           -- the flight being recorded
local ticker
local errored = false

local function safe(fn)
  return function(...)
    local ok, err = pcall(fn, ...)
    if not ok and not errored then
      errored = true
      print(PREFIX .. " error (further errors hidden): " .. tostring(err))
    end
  end
end

local function say(msg)
  if db and db.settings and db.settings.quiet then return end
  print(PREFIX .. " " .. msg)
end

local function say_always(msg) print(PREFIX .. " " .. msg) end

local function round(v, d)
  local m = 10 ^ d
  return math.floor(v * m + 0.5) / m
end

local function mmss(s)
  s = math.floor((s or 0) + 0.5)
  return string.format("%d:%02d", math.floor(s / 60), s % 60)
end

local function onTaxi()
  return UnitOnTaxi and UnitOnTaxi("player") and true or false
end

local function after(sec, fn)
  if C_Timer and C_Timer.After then C_Timer.After(sec, safe(fn)) end
end

---------------------------------------------------------------------------
-- DB
---------------------------------------------------------------------------
local function initDB()
  if type(FlightRecorderDB) ~= "table" then FlightRecorderDB = {} end
  local d = FlightRecorderDB
  if d.version == nil then d.version = 1 end
  if type(d.settings) ~= "table" then d.settings = {} end
  for k, v in pairs(DEFAULTS) do
    if type(d.settings[k]) ~= type(v) then d.settings[k] = v end
  end
  if type(d.flights) ~= "table" then d.flights = {} end
  db = d
end

---------------------------------------------------------------------------
-- Map helpers
---------------------------------------------------------------------------
local continentCache = {}
local CONTINENT_TYPE = (Enum and Enum.UIMapType and Enum.UIMapType.Continent) or 2

local function continentOf(mapID)
  if not mapID then return nil end
  if continentCache[mapID] then return continentCache[mapID] end
  if not (C_Map and C_Map.GetMapInfo) then return nil end
  local id = mapID
  for _ = 1, 20 do
    local info = C_Map.GetMapInfo(id)
    if not info then return nil end
    if info.mapType == CONTINENT_TYPE then
      continentCache[mapID] = id
      return id
    end
    if not info.parentMapID or info.parentMapID == 0 then return nil end
    id = info.parentMapID
  end
  return nil
end

local function bestMap()
  if C_Map and C_Map.GetBestMapForUnit then return C_Map.GetBestMapForUnit("player") end
end

local function mapName(id)
  if C_Map and C_Map.GetMapInfo then
    local info = C_Map.GetMapInfo(id)
    return info and info.name
  end
end

---------------------------------------------------------------------------
-- Pick-up
---------------------------------------------------------------------------
local function onTakeTaxiNode(slot)
  if not (db and db.settings.enabled) then return end
  local p = { time = GetTime() }
  p.taxiMap = GetTaxiMapID and GetTaxiMapID() or nil

  local ids
  if p.taxiMap and C_TaxiMap and C_TaxiMap.GetAllTaxiNodes then
    local ok, list = pcall(C_TaxiMap.GetAllTaxiNodes, p.taxiMap)
    if ok and type(list) == "table" then
      ids = {}
      for _, n in ipairs(list) do
        if n.slotIndex and n.nodeID then ids[n.slotIndex] = n.nodeID end
      end
    end
  end
  local function nodeID(i) return ids and i and ids[i] or nil end
  local function nodeName(i)
    local n = TaxiNodeName and i and TaxiNodeName(i)
    return type(n) == "string" and n or nil
  end

  local curSlot
  if NumTaxiNodes and TaxiNodeGetType then
    for i = 1, NumTaxiNodes() do
      if TaxiNodeGetType(i) == "CURRENT" then curSlot = i; break end
    end
  end
  p.from = nodeName(curSlot)
  p.to = nodeName(slot)
  p.fromNode = nodeID(curSlot)
  p.toNode = nodeID(slot)

  if GetNumRoutes and TaxiGetNodeSlot then
    local ok, hops = pcall(function()
      local n = GetNumRoutes(slot)
      if not n or n <= 1 then return nil end
      local list = {}
      for r = 1, n do
        local a, b = TaxiGetNodeSlot(slot, r, true), TaxiGetNodeSlot(slot, r, false)
        list[#list + 1] = { nodeName(a), nodeName(b), nodeID(a), nodeID(b) }
      end
      return list
    end)
    if ok and hops then p.hops = hops end
  end
  pick = p
end

---------------------------------------------------------------------------
-- Recording
---------------------------------------------------------------------------
local function elapsed()
  return rec.offset + (GetTime() - rec.start)
end

local function dist2(a, b)
  local dy, dx = a[2] - b[2], a[3] - b[3]
  return math.sqrt(dy * dy + dx * dx)
end

-- take one sample; force = keep even if barely moved
local function takeSample(force)
  if not rec then return end
  local f = rec.flight
  local y, x
  if UnitPosition then y, x = UnitPosition("player") end

  -- zone tracking and continent
  local mapID = bestMap()
  local t = round(elapsed(), 1)
  if mapID and mapID ~= rec.lastMap then
    rec.lastMap = mapID
    f.zones[#f.zones + 1] = { t, mapID, mapName(mapID) }
  end
  if not f.continent and mapID then f.continent = continentOf(mapID) end

  if type(y) ~= "number" or type(x) ~= "number" then return end
  local pts = f.points
  local last = pts[#pts]
  local cx, cy
  if f.continent and C_Map and C_Map.GetPlayerMapPosition then
    local pos = C_Map.GetPlayerMapPosition(f.continent, "player")
    if pos and pos.GetXY then
      local px, py = pos:GetXY()
      if px and py then cx, cy = round(px, 5), round(py, 5) end
    end
  end
  local s = { t, round(y, 1), round(x, 1), cx, cy }
  if last and not force and dist2(last, s) < MIN_MOVE then return end
  pts[#pts + 1] = s
end

local function computeStats(f)
  local pts = f.points
  local d = 0
  for i = 2, #pts do d = d + dist2(pts[i - 1], pts[i]) end
  f.distance = math.floor(d + 0.5)
  local last = pts[#pts]
  f.duration = last and round(last[1], 1) or round(rec and elapsed() or 0, 1)
end

local function stopTicker()
  if ticker then ticker:Cancel(); ticker = nil end
end

local function finish(note, complete)
  if not rec then return end
  local r = rec
  stopTicker()
  pcall(takeSample, true)
  local f = r.flight
  -- drop trailing samples taken after the player stopped moving
  local pts = f.points
  while #pts >= 2 and dist2(pts[#pts], pts[#pts - 1]) < MIN_MOVE do pts[#pts] = nil end
  computeStats(f)
  f.complete = complete
  f.note = note
  f.savedAt = nil
  rec = nil
  db.flights[#db.flights + 1] = f
  say(string.format("saved %s -> %s: %s, %d yd, %d points",
    f.from or "?", f.to or "?", mmss(f.duration), f.distance, #f.points))
end

local function landNote()
  if rec.resumed then return "resumed", true end
  if rec.joined then return "joined mid-flight", false end
  return "landed", true
end

local function abortRecording()
  local r = rec
  stopTicker()
  rec = nil
  if r.resumed then
    local f = r.flight
    for i = #f.points, (r.resumeLen or 0) + 1, -1 do f.points[i] = nil end
    for i = #f.zones, (r.resumeZones or 0) + 1, -1 do f.zones[i] = nil end
    computeStats(f)
    f.complete = false
    f.note = "logout"
    f.savedAt = r.savedAt
    db.flights[#db.flights + 1] = f
  end
  say("no flight detected, recording discarded")
end

local function tick()
  if not rec then stopTicker(); return end
  local t = elapsed()
  if t > MAX_SECS then finish("timeout", false); return end

  -- speed from raw position readings (independent of the deduped samples) and from GetUnitSpeed
  local now = GetTime()
  local y, x
  if UnitPosition then y, x = UnitPosition("player") end
  local measured
  if type(y) == "number" and type(x) == "number" then
    if not rec.lastT then
      rec.lastY, rec.lastX, rec.lastT = y, x, now
    else
      local dt = now - rec.lastT
      if dt > 0.05 then
        local dy, dx = y - rec.lastY, x - rec.lastX
        measured = math.sqrt(dy * dy + dx * dx) / dt
        rec.lastY, rec.lastX, rec.lastT = y, x, now
      end
    end
  end
  local gs = GetUnitSpeed and GetUnitSpeed("player")
  if type(gs) ~= "number" then gs = nil end
  local speed = measured or gs
  if math.max(measured or 0, gs or 0) >= SPEED_LIMIT then
    rec.fast = true
    rec.slowSince = nil
  elseif rec.fast and speed then
    rec.slowSince = rec.slowSince or now
  end

  -- phantom guard: never reached taxi speed within 10 s
  if not rec.fast and (now - rec.start) > 10 then
    abortRecording()
    return
  end
  local landed = not onTaxi()
    or (rec.fast and rec.slowSince and (GetTime() - rec.slowSince) >= SLOW_SECS)
  if landed then
    local note, complete = landNote()
    finish(note, complete)
    return
  end
  takeSample(false)
end

local function newFlight()
  return {
    char = UnitName("player"),
    faction = UnitFactionGroup and UnitFactionGroup("player") or nil,
    class = UnitClass and select(2, UnitClass("player")) or nil,
    started = time(),
    zones = {},
    points = {},
  }
end

local function beginRecording(f, offset, flags)
  rec = { flight = f, start = GetTime(), offset = offset or 0, fast = false }
  if flags then
    for k, v in pairs(flags) do rec[k] = v end
  end
  local pts = f.points
  local lastPt = pts[#pts]
  -- zones resumed from a saved flight: avoid duplicating the current zone
  local zs = f.zones[#f.zones]
  if zs then rec.lastMap = zs[2] end
  if rec.resumed then
    rec.resumeLen = #pts
    rec.resumeZones = #f.zones
  end
  stopTicker()
  takeSample(lastPt == nil)
  local interval = (db and db.settings.interval) or 0.5
  if C_Timer and C_Timer.NewTicker then
    ticker = C_Timer.NewTicker(interval, safe(tick))
  end
  say("recording " .. (f.from or "?") .. " -> " .. (f.to or "?"))
end

local function tryStart()
  if rec or not (db and db.settings.enabled) then return end
  if not onTaxi() then return end
  if not pick or (GetTime() - pick.time) > PICK_MAX_AGE then return end
  local p = pick
  pick = nil
  local f = newFlight()
  f.from, f.to, f.fromNode, f.toNode = p.from, p.to, p.fromNode, p.toNode
  f.hops, f.taxiMap = p.hops, p.taxiMap
  beginRecording(f, 0)
end

local function onEnteringWorld()
  if rec or not (db and db.settings.enabled) then return end
  if not onTaxi() then return end
  local flights = db.flights
  local last = flights[#flights]
  if last and last.note == "logout" and type(last.savedAt) == "number"
     and math.abs(time() - last.savedAt) <= 120 then
    flights[#flights] = nil
    local lastPt = last.points[#last.points]
    local offset = (lastPt and lastPt[1] or last.duration or 0) + (time() - last.savedAt)
    last.zones = last.zones or {}
    last.points = last.points or {}
    beginRecording(last, offset, { resumed = true, savedAt = last.savedAt })
  else
    local f = newFlight()
    beginRecording(f, 0, { joined = true })
  end
end

local function onLogout()
  if not rec then return end
  local r = rec
  stopTicker()
  pcall(takeSample, true)
  local f = r.flight
  computeStats(f)
  f.complete = false
  f.note = "logout"
  f.savedAt = time()
  rec = nil
  db.flights[#db.flights + 1] = f
end

---------------------------------------------------------------------------
-- Events
---------------------------------------------------------------------------
local frame = CreateFrame("Frame")
local handlers = {}

handlers.ADDON_LOADED = function(name)
  if name ~= "FlightRecorder" then return end
  initDB()
end

handlers.PLAYER_CONTROL_LOST = function()
  after(0.5, tryStart)
end

handlers.PLAYER_CONTROL_GAINED = function()
  if not rec then return end
  after(0.5, function()
    if rec and not onTaxi() then
      local note, complete = landNote()
      finish(note, complete)
    end
  end)
end

handlers.PLAYER_ENTERING_WORLD = function()
  onEnteringWorld()
  after(2, onEnteringWorld)
end

handlers.PLAYER_LOGOUT = onLogout

frame:SetScript("OnEvent", safe(function(_, event, ...)
  local h = handlers[event]
  if h then h(...) end
end))
for ev in pairs(handlers) do pcall(frame.RegisterEvent, frame, ev) end

if hooksecurefunc and TakeTaxiNode then
  hooksecurefunc("TakeTaxiNode", safe(function(slot)
    onTakeTaxiNode(slot)
    after(0.5, tryStart)
    after(1.5, tryStart)
    after(3, tryStart)
  end))
end

---------------------------------------------------------------------------
-- Slash commands
---------------------------------------------------------------------------
local function flightLine(i, f)
  return string.format("#%d %s: %s -> %s, %s, %d yd, %d points%s",
    i, tostring(f.char or "?"), tostring(f.from or "?"), tostring(f.to or "?"),
    mmss(f.duration), f.distance or 0, f.points and #f.points or 0,
    f.complete and "" or " (partial)")
end

local function slash(msg)
  if not db then initDB() end
  local cmd, rest = (msg or ""):match("^(%S*)%s*(.-)%s*$")
  cmd = (cmd or ""):lower()
  local s = db.settings
  if cmd == "" or cmd == "help" then
    say_always("commands (/frec or /flightrec):")
    print("  status - settings and current recording")
    print("  list [n] - last n flights (default 10)")
    print("  delete <index> - delete one flight")
    print("  clear confirm - delete all flights")
    print("  on / off - enable or disable recording")
    print("  quiet - toggle chat output")
    print("  interval <seconds> - sample interval (0.2-5)")
  elseif cmd == "status" then
    say_always(string.format("enabled=%s quiet=%s interval=%ss flights saved=%d",
      tostring(s.enabled), tostring(s.quiet), tostring(s.interval), #db.flights))
    if rec then
      say_always(string.format("recording now: %s -> %s, %d points so far",
        rec.flight.from or "?", rec.flight.to or "?", #rec.flight.points))
    else
      say_always("not recording")
    end
  elseif cmd == "list" then
    local n = tonumber(rest) or 10
    n = math.max(1, math.floor(n))
    local total = #db.flights
    if total == 0 then say_always("no flights saved"); return end
    for i = math.max(1, total - n + 1), total do
      print(flightLine(i, db.flights[i]))
    end
  elseif cmd == "delete" then
    local i = tonumber(rest)
    if i and db.flights[i] then
      table.remove(db.flights, i)
      say_always("deleted flight #" .. i)
    else
      say_always("usage: /frec delete <index> (1-" .. #db.flights .. ")")
    end
  elseif cmd == "clear" then
    if rest:lower() == "confirm" then
      db.flights = {}
      say_always("all flights deleted")
    else
      say_always("this deletes all " .. #db.flights .. " flights. Type /frec clear confirm to proceed.")
    end
  elseif cmd == "on" then
    s.enabled = true; say_always("recording enabled")
  elseif cmd == "off" then
    s.enabled = false; say_always("recording disabled")
  elseif cmd == "quiet" then
    s.quiet = not s.quiet
    say_always("quiet " .. (s.quiet and "on" or "off"))
  elseif cmd == "interval" then
    local v = tonumber(rest)
    if not v then say_always("usage: /frec interval <seconds> (0.2-5)"); return end
    s.interval = math.max(0.2, math.min(5, v))
    say_always("interval " .. s.interval .. "s (applies to the next flight)")
  else
    say_always("unknown command; try /frec help")
  end
end

SLASH_FLIGHTRECORDER1 = "/frec"
SLASH_FLIGHTRECORDER2 = "/flightrec"
SlashCmdList["FLIGHTRECORDER"] = safe(slash)
