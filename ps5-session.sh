#!/usr/bin/env bash
# PS5 (CachyOS) session integration, used by install-cachyos.sh.
#
# The PS5 setup picks the tty1 session from a token file, ~/.config/ps5-next-session
# ("gamescope" | "desktop"), read by /etc/profile.d/ps5-tty-session.sh, and
# ps5-session-default.service resets it to "gamescope" at every boot.
# This adds "crossbar" as a third token and makes it the boot default:
#   - two small marked blocks in ps5-tty-session.sh (a backup is kept)
#   - a drop-in for ps5-session-default.service that writes "crossbar" instead
# Crossbar's "Switch to Gaming Mode / Desktop" just write the token and leave;
# "Return to Crossbar" writes "crossbar" back.
#
#   ps5-session.sh detect            exit 0 if this is that PS5 setup
#   ps5-session.sh install USER      (root)
#   ps5-session.sh uninstall USER    (root) back to gaming mode as the default
set -euo pipefail
SCRIPT=${PS5_TTY_SCRIPT:-/etc/profile.d/ps5-tty-session.sh}
UNIT=ps5-session-default.service
DROPIN=${PS5_DROPIN_ROOT:-}/etc/systemd/system/$UNIT.d/zz-crossbar.conf
BACKUP=${PS5_DROPIN_ROOT:-}/var/lib/crossbar/ps5-tty-session.sh.orig
BEGIN="# >>> crossbar >>>"
END="# <<< crossbar <<<"

detect() { [[ -f "$SCRIPT" ]] && grep -q 'ps5-next-session' "$SCRIPT"; }

case "${1:-}" in
  detect) detect; exit $? ;;
  install|uninstall) ;;
  *) echo "usage: $0 detect | install USER | uninstall USER"; exit 2 ;;
esac
[[ $EUID -eq 0 ]] || { echo "run as root"; exit 1; }
U="${2:?user}"
UHOME=$(getent passwd "$U" | cut -d: -f6)
TOKEN="$UHOME/.config/ps5-next-session"
detect || { echo "not the PS5 tty session setup"; exit 1; }

strip_blocks() { sed -i "/^[[:space:]]*$BEGIN\$/,/^[[:space:]]*$END\$/d" "$SCRIPT"; }

if [[ "$1" == uninstall ]]; then
  strip_blocks
  rm -f "$DROPIN"; rmdir "$(dirname "$DROPIN")" 2>/dev/null || true
  systemctl daemon-reload 2>/dev/null || true
  [[ "$(cat "$TOKEN" 2>/dev/null)" == crossbar ]] && echo gamescope >"$TOKEN"
  echo "PS5 session switcher restored: gaming mode is the default again."
  exit 0
fi

mkdir -p "$(dirname "$BACKUP")"
[[ -f "$BACKUP" ]] || cp -a "$SCRIPT" "$BACKUP"
strip_blocks       # re-running the installer replaces the blocks, never duplicates them

python3 - "$SCRIPT" "$BEGIN" "$END" <<'PY'
import sys
path, begin, end = sys.argv[1:]
s = open(path).read()

# 1) before the session switch: the "crossbar" token starts Crossbar
anchor = 'case "$SESSION" in\n'
i = s.find(anchor)
if i < 0:
    sys.exit("couldn't find the session switch in " + path)
block1 = (f"{begin}\n"
          "# Crossbar: a third session choice (token \"crossbar\"), added by install-cachyos.sh.\n"
          "# Not exec'd: if it dies right away we fall back to gaming mode instead of making\n"
          "# getty respawn in a loop. When it exits normally, the token it left decides what's next.\n"
          "if [ \"$SESSION\" = crossbar ] && [ -x /usr/local/bin/crossbar-session ]; then\n"
          "  _cb_t=$(date +%s)\n"
          "  /usr/local/bin/crossbar-session\n"
          "  if [ $(( $(date +%s) - _cb_t )) -lt 15 ]; then\n"
          "    echo \"$(date) Crossbar exited right away (see ~/.cache/sway.log); gaming mode instead\" >>/tmp/ps5-tty-session.log\n"
          "    echo gamescope >\"$SESSION_FILE\"\n"
          "  fi\n"
          "  read -r SESSION <\"$SESSION_FILE\" 2>/dev/null || SESSION=gamescope\n"
          "  SESSION=$(printf '%s' \"$SESSION\" | tr -d '\\r\\n\\t ')\n"
          "  # still \"crossbar\" (Restart / Exit Crossbar): log in again, which starts it again\n"
          "  if [ \"$SESSION\" = crossbar ]; then unset PS5_TTY_SESSION_INIT; exit 0; fi\n"
          "elif [ \"$SESSION\" = crossbar ]; then\n"
          "  SESSION=gamescope   # Crossbar not installed any more\n"
          "fi\n"
          f"{end}\n")
s = s[:i] + block1 + s[i:]

# 2) after Plasma exits: if "Return to Crossbar" chose it, start Crossbar instead of gaming mode
anchor2 = '    [ "$rv" = 0 ] || echo "$(date) plasma session exited rv=$rv" >>"$LOG"\n'
j = s.find(anchor2)
if j >= 0:
    j += len(anchor2)
    block2 = (f"    {begin}\n"
              "    # \"Return to Crossbar\" from Plasma: log in again, which starts Crossbar\n"
              "    if [ \"$(cat \"$SESSION_FILE\" 2>/dev/null)\" = crossbar ]; then unset PS5_TTY_SESSION_INIT; exit 0; fi\n"
              f"    {end}\n")
    s = s[:j] + block2 + s[j:]
else:
    print("note: Plasma exit hook not added (script layout differs); Return to Crossbar from Plasma goes via gaming mode")
open(path, "w").write(s)
PY
bash -n "$SCRIPT" || { echo "patched script failed a syntax check; restoring the original"; cp -a "$BACKUP" "$SCRIPT"; exit 1; }

mkdir -p "$(dirname "$DROPIN")"
cat >"$DROPIN" <<EOF2
# Added by Crossbar's install-cachyos.sh: boot into Crossbar instead of gaming mode.
# Remove with ./install-cachyos.sh --uninstall
[Service]
ExecStart=
ExecStart=/bin/bash -c '/bin/echo crossbar > $TOKEN'
EOF2
systemctl daemon-reload 2>/dev/null || true
echo crossbar >"$TOKEN"; chown "$U:" "$TOKEN"
echo "Crossbar added to the PS5 session switcher and set as the boot default."
echo "  original script backed up to $BACKUP"
