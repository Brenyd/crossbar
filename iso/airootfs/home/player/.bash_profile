[[ -f ~/.bashrc ]] && . ~/.bashrc
# Boot straight into the Crossbar shell on the first console.
if [[ -z $WAYLAND_DISPLAY && $(tty) == /dev/tty1 ]]; then
  exec /usr/local/bin/crossbar-session
fi
