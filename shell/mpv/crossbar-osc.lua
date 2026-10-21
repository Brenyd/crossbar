-- Crossbar video control panel for mpv.
-- Console-style: works with a d-pad and four buttons. Input arrives either as
-- keys (keyboard) or as `script-message crossbar-input <action>` from crossbard
-- (gamepads). Actions: up down left right ok back menu prev next toggle
-- TV remotes add: play pause stop rewind fast_forward channel_up channel_down
-- last_channel subtitles audio_track digit:N (type a channel number, OK or a pause enters it)
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
local note_text, note_until = "", 0       -- a short message drawn even with the panel hidden
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

-- Button glyphs (Xbox / PlayStation / Nintendo) written by Crossbar when playback starts.
local GLYPHS = { ok = "A", back = "B", menu = "Y", prev = "LB", next = "RB", home = "View+Menu" }
local glyphs_checked = -10
local function glyph(action)
  local now = mp.get_time()
  if now - glyphs_checked > 3 then        -- re-read now and then: the style can change in Settings
    glyphs_checked = now
    local path = mp.get_opt("crossbar-glyphs")
    local f = path and io.open(path, "r")
    if f then
      local ok, utils = pcall(require, "mp.utils")
      local data = ok and utils.parse_json(f:read("*a")) or nil
      f:close()
      if data and data.actions then for k, v in pairs(data.actions) do GLYPHS[k] = v end end
    end
  end
  return GLYPHS[action] or action
end

local function note_event()
  if mp.get_time() >= note_until or note_text == "" then return nil end
  return rect(80, 60, 900, 110, "000000", "50") ..
    "\n{\\an4\\pos(120,115)\\fnNoto Sans\\fs52\\bord0\\shad2\\1c&HFFFFFF&}" .. esc(note_text)
end

local function draw()
  if not visible then
    local n = note_event()
    if n then
      ov.data = n
      ov:update()
    else
      ov:remove()
    end
    return
  end
  local ev = {}
  local n = note_event()
  if n then ev[#ev + 1] = n end
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
  local n, gap, cy = #BUTTONS, 160, 950
  local x0 = 960 - (n - 1) * gap / 2
  for i, b in ipairs(BUTTONS) do
    local cx = x0 + (i - 1) * gap
    if i == focus then
      ev[#ev + 1] = rect(cx - 66, cy - 50, 132, 100, "FFFFFF", "B8")
      ev[#ev + 1] = rect(cx - 66, cy + 48, 132, 4, "FFFFFF", "00")
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
      ev[#ev + 1] = string.format("{\\an7\\pos(%d,%d)\\fscx140\\fscy140\\bord0\\shad0\\1c&HFFFFFF&\\1a&H%s&\\p1}%s{\\p0}",
        cx - 28, cy - 28, alpha, ICON[id])
    end
  end

  local b = BUTTONS[focus]
  local extra = ""
  if b.id == "subs" then extra = ": " .. track_label("sub") end
  if b.id == "audio" then extra = ": " .. track_label("audio") end
  ev[#ev + 1] = string.format("{\\an8\\pos(960,1008)\\fnNoto Sans\\fs32\\bord0\\shad1\\1c&HFFFFFF&}%s%s",
    esc(b.label), esc(extra))
  ev[#ev + 1] = "{\\an2\\pos(960,1072)\\fnNoto Sans\\fs22\\bord0\\shad0\\1c&HBBBBBB&}" ..
    esc("◀ ▶  choose     " .. glyph("ok") .. "  select     " .. glyph("back") .. "  hide     ▲ ▼  volume     " ..
        glyph("prev") .. "/" .. glyph("next") .. "  skip     " .. glyph("home") .. "  Quick Menu")

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

local function is_live()
  local d = mp.get_property_native("duration")
  return not d or d <= 0
end

local function prev_item()
  if not is_live() and (mp.get_property_native("time-pos") or 0) > 5 then
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

local function note(text, secs)
  note_text, note_until = text, mp.get_time() + (secs or 2.5)
  draw()
end

-- channel numbers and the last channel (a live TV list plays as a playlist: channel N = item N)
local cur_pos, last_pos = nil, nil
mp.observe_property("playlist-pos", "number", function(_, p)
  if p and p >= 0 and p ~= cur_pos then last_pos, cur_pos = cur_pos, p end
end)
local digits, digits_timer = "", nil

local function go_channel(n)
  local count = mp.get_property_native("playlist-count") or 0
  if n >= 1 and n <= count then
    mp.set_property_native("playlist-pos", n - 1)
    note(string.format("%d", n), 2)
  else
    note(string.format("No channel %d (1 – %d)", n, count), 2.5)
  end
end

local function commit_digits()
  if digits_timer then digits_timer:kill(); digits_timer = nil end
  local n = tonumber(digits)
  digits = ""
  if n then go_channel(n) end
end

local function remote_act(a)
  local d = a:match("^digit:(%d)$")
  if d then
    digits = (digits .. d):sub(-4)
    note(digits .. "_", 3)
    if digits_timer then digits_timer:kill() end
    digits_timer = mp.add_timeout(1.8, commit_digits)
    return true
  end
  if a == "ok" and digits ~= "" then commit_digits(); return true end
  if a == "play" then mp.set_property_native("pause", false); show(); return true end
  if a == "pause" then mp.set_property_native("pause", true); show(); return true end
  if a == "stop" then press("stop"); return true end
  if a == "rewind" then mp.commandv("seek", -10); show(); return true end
  if a == "fast_forward" then mp.commandv("seek", 30); show(); return true end
  if a == "channel_up" or a == "channel_down" then
    mp.command(a == "channel_up" and "playlist-next" or "playlist-prev"); show(); return true
  end
  if a == "last_channel" then
    if last_pos then mp.set_property_native("playlist-pos", last_pos); show() else note("No previous channel") end
    return true
  end
  if a == "subtitles" then mp.command("cycle sub"); note("Subtitles: " .. track_label("sub")); return true end
  if a == "audio_track" then mp.command("cycle audio"); note("Audio: " .. track_label("audio")); return true end
  return false
end

local function act(a)
  if remote_act(a) then return end
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

-- Keyboard: the same mapping as the XMB (Settings > Controller & Keyboard).
local MPV_KEYS = { ArrowUp = "UP", ArrowDown = "DOWN", ArrowLeft = "LEFT", ArrowRight = "RIGHT",
  Enter = "ENTER", Escape = "ESC", Tab = "TAB", Space = "SPACE", Backspace = "BS", Home = "HOME",
  End = "END", PageUp = "PGUP", PageDown = "PGDWN", Insert = "INS", Delete = "DEL" }
local DEFAULT_KEYS = { up = { "ArrowUp" }, down = { "ArrowDown" }, left = { "ArrowLeft" }, right = { "ArrowRight" },
  ok = { "Enter", "Space" }, back = { "Escape", "Backspace" }, menu = { "Tab", "t" },
  prev = { "PageUp" }, next = { "PageDown" }, toggle = { "p" } }

local function load_keys()
  local path = mp.get_opt("crossbar-controls")
  if path then
    local f = io.open(path, "r")
    if f then
      local ok, utils = pcall(require, "mp.utils")
      local data = ok and utils.parse_json(f:read("*a")) or nil
      f:close()
      if data and data.keyboard then return data.keyboard end
    end
  end
  return DEFAULT_KEYS
end

local function mpv_key(k)
  if MPV_KEYS[k] then return MPV_KEYS[k] end
  if #k > 1 and k:sub(1, 1) == "F" and tonumber(k:sub(2)) then return k end
  if #k == 1 then return k:lower() end
  return nil
end

local bound = 0
for action, list in pairs(load_keys()) do
  if action ~= "home" then           -- home is handled by sway for every app
    for _, k in ipairs(list) do
      local key = mpv_key(k)
      if key then
        bound = bound + 1
        local a = action
        mp.add_forced_key_binding(key, "crossbar-key-" .. bound, function() act(a) end,
          { repeatable = (a == "up" or a == "down" or a == "left" or a == "right") })
      end
    end
  end
end
mp.add_forced_key_binding("KP_ENTER", "crossbar-kpenter", function() act("ok") end)

-- Fallback when Crossbar's controller service can't read the pad: mpv reads it
-- itself (--input-gamepad) and these bindings drive the same panel.
if mp.get_opt("crossbar-gamepad") == "yes" then
  local PAD = {
    GAMEPAD_DPAD_UP = "up", GAMEPAD_DPAD_DOWN = "down", GAMEPAD_DPAD_LEFT = "left", GAMEPAD_DPAD_RIGHT = "right",
    GAMEPAD_LEFT_STICK_UP = "up", GAMEPAD_LEFT_STICK_DOWN = "down",
    GAMEPAD_LEFT_STICK_LEFT = "left", GAMEPAD_LEFT_STICK_RIGHT = "right",
    GAMEPAD_ACTION_DOWN = "ok", GAMEPAD_ACTION_RIGHT = "back", GAMEPAD_ACTION_UP = "menu", GAMEPAD_ACTION_LEFT = "menu",
    GAMEPAD_LEFT_SHOULDER = "prev", GAMEPAD_RIGHT_SHOULDER = "next", GAMEPAD_START = "toggle", GAMEPAD_BACK = "menu",
  }
  for key, a in pairs(PAD) do
    mp.add_forced_key_binding(key, "crossbar-pad-" .. key, function() act(a) end,
      { repeatable = (a == "up" or a == "down") })
  end
  mp.add_forced_key_binding("GAMEPAD_GUIDE", "crossbar-pad-guide", function()
    mp.commandv("run", "/usr/local/bin/crossbar-home")
  end)
end
mp.add_forced_key_binding("MOUSE_MOVE", "crossbar-mouse", function() show() end)
mp.add_forced_key_binding("MBTN_LEFT", "crossbar-click", function() act(visible and "toggle" or "menu") end)

mp.register_event("file-loaded", function() focus = 3; show(3) end)
mp.observe_property("pause", "bool", function(_, p) if p then show(3600) elseif visible then show() end end)

mp.add_periodic_timer(0.25, function()
  if visible and mp.get_time() > hide_at then
    visible = false
  end
  if mp.get_time() >= note_until then note_text = "" end
  draw()
end)
