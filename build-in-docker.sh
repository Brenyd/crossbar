#!/usr/bin/env bash
# Build the ISO inside an Arch container — works from any Linux distro with Docker or Podman.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE="$(command -v podman || command -v docker)"
"$ENGINE" run --rm --privileged -v "$HERE":/src:Z docker.io/archlinux:latest bash -c '
  pacman -Syu --noconfirm --needed archiso python-pip &&
  OUT=/src/out WORK=/tmp/crossbar-build /src/build-iso.sh'
