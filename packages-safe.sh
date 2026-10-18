# Sourced by install-cachyos.sh and update-system.sh: install packages WITHOUT ever letting
# pacman pull in (or swap) a kernel. Some packages (e.g. wine) depend on a virtual
# "ntsync-module" that only kernels provide; on a PS5 the kernel is a custom build
# (linux-ps5) and a stock one must never replace it.

# Kernels and their headers: linux, linux-zen, linux-cachyos-bore, linux-ps5-headers…
KERNEL_RE='^linux(-[a-z0-9._]+)*$'
NOT_KERNEL_RE='^linux-(firmware.*|api-headers|tools.*|pam.*|meta.*)$'
# Tell pacman these kernel-provided virtual packages are already satisfied.
PAC_SAFE=(--needed --noconfirm --assume-installed ntsync-module --assume-installed NTSYNC-MODULE)

# Learn any other kernel-only virtual packages from pacman itself ("N providers available for X",
# where the providers are kernels) and mark those as satisfied too.
learn_virtuals() {
  local out name
  out=$(pacman -S "${PAC_SAFE[@]}" --print-format '%n' "$@" 2>&1 </dev/null || true)
  while read -r name; do
    [[ -n "$name" ]] || continue
    case " ${PAC_SAFE[*]} " in *" $name "*) ;; *) PAC_SAFE+=(--assume-installed "$name"); echo "  (treating $name as provided by your kernel)";; esac
  done < <(grep -oE 'providers available for [^:]+' <<<"$out" | sed 's/providers available for //' | sort -u)
}
_plan() { pacman -S "${PAC_SAFE[@]}" --print-format '%n' "$@" 2>/dev/null </dev/null; }
# (no grep -q at the end of the pipe: with pipefail its early exit could read as "no kernel")
pulls_kernel() { [[ -n "$(_plan "$@" | grep -E "$KERNEL_RE" | grep -vE "$NOT_KERNEL_RE" || true)" ]]; }

# safe_install pkg... : installs what it can; sets FAILED (not in repos / failed) and
# KERNEL_SKIPPED (would have needed a kernel) arrays.
safe_install() {
  FAILED=(); KERNEL_SKIPPED=()
  local ok=() p
  learn_virtuals "$@"
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
  if ! pacman -S "${PAC_SAFE[@]}" "${ok[@]}" </dev/null; then
    # one bad name fails the whole batch: retry one by one
    for p in "${ok[@]}"; do
      pacman -T "$p" >/dev/null 2>&1 && continue
      echo "-- $p:"
      pacman -S "${PAC_SAFE[@]}" "$p" </dev/null 2>&1 | tail -n 6 || true
      pacman -T "$p" >/dev/null 2>&1 || FAILED+=("$p")
    done
  fi
}
