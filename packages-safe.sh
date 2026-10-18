# Sourced by install-cachyos.sh and update-system.sh: install packages WITHOUT ever letting
# pacman pull in (or swap) a kernel. Some packages (e.g. wine) depend on a virtual
# "ntsync-module" that only kernels provide; on a PS5 the kernel is a custom build
# (linux-ps5) and a stock one must never replace it.

# Kernels and their headers: linux, linux-zen, linux-cachyos-bore, linux-ps5-headers…
KERNEL_RE='^linux(-[a-z0-9._]+)*$'
NOT_KERNEL_RE='^linux-(firmware.*|api-headers|tools.*|pam.*|meta.*)$'
# Tell pacman these kernel-provided virtual packages are already satisfied.
PAC_SAFE=(--needed --noconfirm --assume-installed ntsync-module --assume-installed NTSYNC-MODULE)

_plan() { pacman -S "${PAC_SAFE[@]}" --print-format '%n' "$@" 2>/dev/null; }
# (no grep -q at the end of the pipe: with pipefail its early exit could read as "no kernel")
pulls_kernel() { [[ -n "$(_plan "$@" | grep -E "$KERNEL_RE" | grep -vE "$NOT_KERNEL_RE" || true)" ]]; }

# safe_install pkg... : installs what it can; sets FAILED (not in repos / failed) and
# KERNEL_SKIPPED (would have needed a kernel) arrays.
safe_install() {
  FAILED=(); KERNEL_SKIPPED=()
  local ok=() p
  if pulls_kernel "$@"; then
    for p in "$@"; do
      if pulls_kernel "$p"; then KERNEL_SKIPPED+=("$p"); else ok+=("$p"); fi
    done
  else
    ok=("$@")
  fi
  if ((${#KERNEL_SKIPPED[@]})); then
    printf '\e[1;33m!! skipped (would install a kernel): %s\e[0m\n' "${KERNEL_SKIPPED[*]}"
  fi
  ((${#ok[@]})) || return 0
  echo "installing: ${ok[*]}"
  if ! pacman -S "${PAC_SAFE[@]}" "${ok[@]}"; then
    # one bad name fails the whole batch: retry one by one
    for p in "${ok[@]}"; do
      pacman -T "$p" >/dev/null 2>&1 && continue
      pacman -S "${PAC_SAFE[@]}" "$p" >/dev/null 2>&1 || FAILED+=("$p")
    done
  fi
}
