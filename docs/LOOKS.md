# Looks (console skins)

A **look** is a whole front end for Crossbar: how the menu, the Options panel, dialogs, toasts
and the Quick Menu are drawn. Crossbar ships three — the **cross-media bar (PS3 style)**, **Blades (Xbox 360, 2005 style)** and the
**Dashboard (Xbox 360, 2011 style)** — and starts in the one chosen in **Settings › Theme › Interface**.
Only that look is loaded (the backend builds it into the page, so the first frame is already
drawn in it); choosing another saves it and reloads the menu.

Underneath, every look runs the *same* menu: the same categories and items, folders, actions,
Options entries, dialogs, keyboard, controller mapping and Quick Menu rows. A look only
decides how they're drawn and how the D-pad moves around them. So a new console skin is a
folder of front-end code — nothing in the backend changes.

> A **theme pack** (docs/THEMES.md) is different: colours, a background picture, a font, icons
> and sounds. Packs dress the cross-media bar fully; other looks use what suits them (the
> Dashboard can use a pack's picture as its background).

## Where looks live

| Folder | What |
|---|---|
| `shell/web/looks/<id>/` | built in (`xmb`, `blades`, `x360`) |
| `~/.local/share/crossbar/looks/<id>/` | yours — they show up in Settings › Theme › Interface with no other change (reload the menu: Settings › System › Restart Crossbar) |
| `shell/web/looks/_template/` | **a working starter look** to copy (it's skipped where it is) |

A look's folder has three files:

```
look.json   name, settings, colours, how the Quick Menu overlay should look
look.js     the drawing code: Shell.register('<id>', {...})
look.css    its styles, every rule scoped to body[data-shell="<id>"]
```

The folder name, `"id"` in look.json and the id passed to `Shell.register` must match
(lowercase letters, digits, `-`, `_`). A look of yours can't replace a built-in one's id.

## Quick start

1. `cp -r shell/web/looks/_template ~/.local/share/crossbar/looks/mylook`
2. In `look.json` set `"id": "mylook"` and a `"name"`; in `look.js` set `const ID = 'mylook'`;
   in `look.css` replace `starter` with `mylook`.
3. Restart Crossbar, then **Settings › Theme › Interface › your look**.

The starter is ~80 lines: categories down the left, items on the right. Grow it from there —
the Dashboard (`looks/x360/`) shows everything a look can do.

## look.json

```json
{
  "id": "mylook",
  "name": "Channels (Wii style)",
  "short": "Wii",
  "description": "One line for Settings",
  "author": "You",
  "order": 20,
  "settings": [
    { "key": "bg", "label": "Background", "icon": "photo", "default": "white",
      "choices": [["white", "White"], ["blue", "Blue"], ["picture", "Theme picture", { "needs": "theme_picture" }]] },
    { "key": "accent", "label": "Accent Colour", "icon": "palette", "default": "blue",
      "choices": [["blue", "Blue"], ["red", "Red"]] }
  ],
  "colors": { "accent": { "blue": ["#2563eb", "#60a5fa"], "red": ["#b91c1c", "#f87171"] } },
  "overlay": { "style": "guide", "accent_setting": "accent", "panel": "#26272b", "panel2": "#1c1d20" }
}
```

- **settings** — each one becomes a row in Settings › Theme (when your look is on) that picks
  one of its `choices` (`[value, label]`, optionally `{"needs": "theme_picture"}` to offer it
  only when the theme pack has a background picture). Crossbar stores, validates and fills in
  defaults; your code reads them with `Looks.settings('<id>')` → `{bg: 'white', accent: 'blue'}`.
- **colors** — named colour sets per setting value; `Looks.colors('<id>', 'accent')` gives the
  current one (`['#2563eb', '#60a5fa']`). The overlay uses them too (below).
- **overlay** — how the native Quick Menu (drawn over games by `overlay.py`) looks while your
  look is on: `"style": "panel"` (the XMB's list), `"guide"` (the Dashboard's: profile, five
  tabs walked with LB / RB, rows lit in your accent) or `"blade"` (Blades': a glossy blade down the
  left in your accent colours, your card on top, rows lit like glass). `accent_setting` names the setting whose
  `colors` entry tints it; `panel` / `panel2` / `text` / `dim` are its colours.
- **order** — where it sits in the Interface list (XMB 0, Blades 5, Dashboard 10).

## look.js: the Shell contract

`Shell.register(id, look)` — the object provides:

| Member | What it does |
|---|---|
| `setup()` / `teardown()` | build your own page (called once, when the menu starts in your look) / remove it |
| `configure(state)` | apply your settings — called on every state update, so keep it cheap |
| `render()` | draw the current page: categories or the open folder, then its items |
| `renderCats()` | the categories (`CATS`, current `S.ci`), or the folder title (`S.stack`) |
| `renderColumn(rebuild)` | build the item nodes: **`columnEls[i]` is the node for `list()[i]`** |
| `itemEl(item)` | one item's node: class `item`, holding `.txt` with `.label`, `.sub` (and `.bar > i` when `item.progress != null`) — the shared code updates those for live downloads |
| `position()` | place the nodes for the current selection (`sel()`) |
| `hint()` | the button hints (`glb('ok')` etc. give the controller's glyphs) |
| `moveV(d)` / `moveH(d)` | the D-pad: change `setSel(i)`, or `S.ci` + `refresh(CATS[S.ci].id)`, or `back()` |
| `resetCats()` | the category row must be rebuilt (new icons from a theme) |

Optional:

| Member | What it does |
|---|---|
| `bumper(d)` | LB / RB on the menu; return `true` if you used them (otherwise they skip tracks) |
| `patched()` | a running download changed some items' text / progress |
| `dialogVertical` | dialog buttons stack vertically (up / down choose) |
| `optionsGeom` | `{TOP, MIN, MAX}`: where the Options list sits and how far it may slide |
| `renderQuick(QuickMenu)` | draw the in-menu Quick Menu yourself (`rows`, `sel`, `page`, `tabs()`, `isTab()`); return `true` |
| `quickTabs` | the Quick Menu is tabbed (Games & Apps, Media, Home, Social, Settings; LB / RB) |
| `settingsRows(state, theme)` | extra rows for Settings › Theme beyond look.json (the XMB's Wave Colour) |

Shared helpers you can use: `list()`, `sel()`, `setSel(i)`, `S` (state: `S.ci`, `S.stack`,
`S.items`), `CATS`, `refresh(cat)`, `back()`, `openFolder(item)`, `icon(name)`, `esc(text)`,
`gl(text)` (glyph tokens), `glb(action)`, `Sfx.move()` / `ok()` / `back()`, `ensureArt(el, item)`
and `artLoaded` (lazy artwork), `Recent.top(cat, items)` (what was used last in a category —
the Dashboard's big tile), `Looks.settings(id)`, `Looks.colors(id, key)`.

Items carry: `key`, `label`, `sub`, `icon` or `art` (+ `artTitle`, `artShape: 'poster' |
'square'`), `badge`, `progress`, `recent` (a timestamp), and `action` or `children`, plus
`options` (the Y menu). Don't call actions yourself: A, B and Y go through the shared code
(`confirm()`, `back()`, `options()`), so every look behaves the same.

## look.css

Scope everything to your look — `body[data-shell="<id>"] …` — so other looks are untouched.
The base styles (`style.css`) give every look working dialogs, toasts, the keyboard and the
Options panel; restyle those under your scope (the Dashboard's `look.css` restyles them all).
Pieces you don't use: hide them (`#cats`, `#crumb`, `#waves`…). A theme pack's `theme.css`
loads after looks, so packs can still restyle any look.

## Tips

- Draw on the 1920×1080 `#stage` (it's scaled to the screen); keep TV-safe margins (~150 px).
- Long text: ellipsis (`white-space: nowrap; overflow: hidden; text-overflow: ellipsis`) or wrap
  it in a details pane — never let it run off the screen.
- Artwork loads lazily: call `ensureArt(el, item)` for the nodes near the selection.
- Test with the demo library: `python3 shell/server.py --demo`, open http://127.0.0.1:7777.
