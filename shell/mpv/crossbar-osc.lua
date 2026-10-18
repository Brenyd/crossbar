-- Crossbar video control panel for mpv.
-- Console-style: works with a d-pad and four buttons. Input arrives either as
-- keys (keyboard) or as `script-message crossbar-input <action>` from crossbard
-- (gamepads). Actions: up down left right ok back menu prev next toggle
--
-- Panel hidden:  A = play/pause, Left/Right = seek -10s/+30s, Up/Down = volume,
--                B = open panel on "Stop", Y = open panel, L1/R1 = prev/next
-- Panel shown:   Left/Right = choose button, A = press it, B = hide

local mp = require "mp"

local ov = mp.create_osd_overlay("ass-events")
ov.res_x, ov.res_y = 1920, 1080

local BUTTONS = {
  { id = "prev",  label = "Previous" },
  { id = "back",  label = "Back 10 seconds" },
  { id = "play",  label = "Play / Pause" },
  { id = "fwd",   label = "Forward 30 seconds" },
  { id = "next",  label = "Next" },
  { id = "subs",  label = "Subtitles" },
  { id = "audio", label = "Audio Track" },
  { id = "stop",  label = "Stop" },
}
local ICON = {
  play  = "m 6 0 l 38 20 l 6 40",
  pause = "m 6 0 l 16 0 l 16 40 l 6 40 m 24 0 l 34 0 l 34 40 l 24 40",
  prev  = "m 2 0 l 8 0 l 8 40 l 2 40 m 38 0 l 38 40 l 10 20",
  next  = "m 32 0 l 38 0 l 38 40 l 32 40 m 2 0 l 30 20 l 2 40",
  back  = "m 20 0 l 20 40 l 0 20 m 40 0 l 40 40 l 20 20",
  fwd   = "m 0 0 l 20 20 l 0 40 m 20 0 l 40 20 l 20 40",
  stop  = "m 4 4 l 36 4 l 36 36 l 4 36",
  audio = "m 2 13 l 12 13 l 24 2 l 24 38 l 12 27 l 2 27 m 29 13 l 32 11 l 36 20 l 32 29 l 29 27 l 32 20",
}

local visible, focus, hide_at, vol_until = false, 3, 0, 0
local TIMEOUT = 4

local function esc(s)
  s = tostring(s or "")
  return (s:gsub("\\", "\\\\"):gsub("{", "\\{"):gsub("}", "\\}"):gsub("\n", " "))
end

local function fmt(t)
  if not t or t < 0 then return "--:--" end
  t = math.floor(t)
  local h, m, s = math.floor(t / 3600), math.floor(t % 3600 / 60), t % 60
  if h > 0 then return string.format("%d:%02d:%02d", h, m, s) end
  return string.format("%d:%02d", m, s)
end

local function track_label(kind)
  local t = mp.get_property_native("current-tracks/" .. kind)
  if not t then return "Off" end
  local parts = {}
  if t.lang then parts[#parts + 1] = t.lang end
  if t.title then parts[#parts + 1] = t.title end
  if #parts == 0 then parts[1] = "Track " .. tostring(t.id) end
  return table.concat(parts, " · ")
end

local function rect(x, y, w, h, color, alpha)
  return string.format("{\\an7\\pos(0,0)\\bord0\\shad0\\1c&H%s&\\1a&H%s&\\p1}m %d %d l %d %d l %d %d l %d %d{\\p0}",
    color, alpha, x, y, x + w, y, x + w, y + h, x, y + h)
end

local function draw()
  if not visible then
    ov:remove()
    return
  end
  local ev = {}
  local paused = mp.get_property_native("pause")
  local pos = mp.get_property_native("time-pos") or 0
  local dur = mp.get_property_native("duration") or 0

  ev[#ev + 1] = rect(0, 730, 1920, 350, "000000", "40")
  ev[#ev + 1] = rect(0, 728, 1920, 2, "FFFFFF", "A0")

  local title = mp.get_property("media-title") or ""
  ev[#ev + 1] = "{\\an7\\pos(120,760)\\fnNoto Sans\\fs46\\bord0\\shad2\\1c&HFFFFFF&}" .. esc(title)
  local count = mp.get_property_native("playlist-count") or 1
  if count > 1 then
    local idx = (mp.get_property_native("playlist-pos") or 0) + 1
    ev[#ev + 1] = string.format("{\\an9\\pos(1800,766)\\fnNoto Sans\\fs30\\bord0\\shad1\\1c&HCCCCCC&}%d / %d", idx, count)
  end

  -- progress
  local frac = (dur > 0) and math.min(1, pos / dur) or 0
  ev[#ev + 1] = rect(120, 846, 1680, 8, "FFFFFF", "C0")
  ev[#ev + 1] = rect(120, 846, math.floor(1680 * frac), 8, "FFFFFF", "00")
  ev[#ev + 1] = string.format("{\\an7\\pos(120,866)\\fnNoto Sans\\fs30\\bord0\\shad1\\1c&HFFFFFF&}%s", fmt(pos))
  ev[#ev + 1] = string.format("{\\an9\\pos(1800,866)\\fnNoto Sans\\fs30\\bord0\\shad1\\1c&HCCCCCC&}-%s", fmt(dur - pos))

  -- buttons
  local n, gap, cy = #BUTTONS, 140, 960
  local x0 = 960 - (n - 1) * gap / 2
  for i, b in ipairs(BUTTONS) do
    local cx = x0 + (i - 1) * gap
    if i == focus then
      ev[#ev + 1] = rect(cx - 56, cy - 42, 112, 84, "FFFFFF", "C8")
      ev[#ev + 1] = rect(cx - 56, cy + 40, 112, 3, "FFFFFF", "00")
    end
    local alpha = (i == focus) and "00" or "50"
    local id = b.id
    if id == "play" then id = paused and "play" or "pause" end
    if id == "subs" then
      ev[#ev + 1] = string.format("{\\an5\\pos(%d,%d)\\fnNoto Sans\\b1\\fs34\\bord2\\3c&HFFFFFF&\\3a&H%s&\\1a&HFF&\\shad0}CC",
        cx, cy, alpha)
      ev[#ev + 1] = string.format("{\\an5\\pos(%d,%d)\\fnNoto Sans\\b1\\fs34\\bord0\\shad0\\1c&HFFFFFF&\\1a&H%s&}CC",
        cx, cy, alpha)
    else
      ev[#ev + 1] = string.format("{\\an7\\pos(%d,%d)\\bord0\\shad0\\1c&HFFFFFF&\\1a&H%s&\\p1}%s{\\p0}",
        cx - 20, cy - 20, alpha, ICON[id])
    end
  end

  local b = BUTTONS[focus]
  local extra = ""
  if b.id == "subs" then extra = ": " .. track_label("sub") end
  if b.id == "audio" then extra = ": " .. track_label("audio") end
  ev[#ev + 1] = string.format("{\\an8\\pos(960,1020)\\fnNoto Sans\\fs28\\bord0\\shad1\\1c&HFFFFFF&}%s%s",
    esc(b.label), esc(extra))

  if mp.get_time() < vol_until then
    local vol = mp.get_property_native("volume") or 0
    ev[#ev + 1] = rect(1560, 80, 280, 70, "000000", "40")
    ev[#ev + 1] = string.format("{\\an5\\pos(1700,115)\\fnNoto Sans\\fs34\\bord0\\shad0\\1c&HFFFFFF&}Volume %d%%", vol)
  end
  if paused then
    ev[#ev + 1] = "{\\an9\\pos(1800,80)\\fnNoto Sans\\fs34\\bord0\\shad2\\1c&HFFFFFF&}Paused"
  end

  ov.data = table.concat(ev, "\n")
  ov:update()
end

local function show(sec)
  visible = true
  -- while paused the panel stays up, like a console player
  hide_at = mp.get_time() + (sec or (mp.get_property_native("pause") and 3600 or TIMEOUT))
  draw()
end

local function hide()
  visible = false
  draw()
end

local function prev_item()
  if (mp.get_property_native("time-pos") or 0) > 5 then
    mp.commandv("seek", 0, "absolute")
  else
    mp.command("playlist-prev")
  end
end

local function press(id)
  if id == "prev" then prev_item()
  elseif id == "back" then mp.commandv("seek", -10)
  elseif id == "play" then mp.command("cycle pause")
  elseif id == "fwd" then mp.commandv("seek", 30)
  elseif id == "next" then mp.command("playlist-next")
  elseif id == "subs" then mp.command("cycle sub")
  elseif id == "audio" then mp.command("cycle audio")
  elseif id == "stop" then
    mp.command(mp.get_property_native("save-position-on-quit") and "quit-watch-later" or "quit")
  end
end

local function act(a)
  if a == "up" or a == "down" then
    mp.commandv("add", "volume", a == "up" and 5 or -5)
    vol_until = mp.get_time() + 1.5
    if not visible then
      visible = true
      hide_at = mp.get_time() + 1.5
    end
    draw()
    return
  end
  if a == "prev" then prev_item(); show(); return end
  if a == "next" then mp.command("playlist-next"); show(); return end
  if a == "toggle" then mp.command("cycle pause"); show(); return end

  if not visible then
    if a == "ok" then mp.command("cycle pause"); show()
    elseif a == "left" then mp.commandv("seek", -10); show()
    elseif a == "right" then mp.commandv("seek", 30); show()
    elseif a == "back" then focus = #BUTTONS; show(8)
    elseif a == "menu" then show()
    end
    return
  end
  if a == "left" then focus = math.max(1, focus - 1); show()
  elseif a == "right" then focus = math.min(#BUTTONS, focus + 1); show()
  elseif a == "ok" then press(BUTTONS[focus].id); show()
  elseif a == "back" or a == "menu" then hide()
  end
end

mp.register_script_message("crossbar-input", act)

local keys = {
  LEFT = "left", RIGHT = "right", UP = "up", DOWN = "down",
  ENTER = "ok", KP_ENTER = "ok", SPACE = "toggle", ESC = "back", BS = "back",
  TAB = "menu", PGUP = "prev", PGDWN = "next",
}
for key, a in pairs(keys) do
  mp.add_forced_key_binding(key, "crossbar-" .. key, function() act(a) end, { repeatable = (a == "left" or a == "right" or a == "up" or a == "down") })
end
mp.add_forced_key_binding("MOUSE_MOVE", "crossbar-mouse", function() show() end)
mp.add_forced_key_binding("MBTN_LEFT", "crossbar-click", function() act(visible and "toggle" or "menu") end)

mp.register_event("file-loaded", function() focus = 3; show(3) end)
mp.observe_property("pause", "bool", function(_, p) if p then show(3600) elseif visible then show() end end)

mp.add_periodic_timer(0.25, function()
  if visible and mp.get_time() > hide_at then
    visible = false
  end
  draw()
end)
