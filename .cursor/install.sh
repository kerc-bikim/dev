#!/usr/bin/env bash
# Idempotent bootstrap for the seismic-tools monorepo.
# Prepares: system libraries (Qt runtime for PyQt5, libsndfile, headless X),
# a shared Python virtualenv, and Node dependencies for both web apps.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

SUDO=""
if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
  SUDO="sudo"
fi

# ---------------------------------------------------------------------------
# 1. System packages
#    - Qt/xcb runtime + libGL/EGL: PyQt5 (recvQSCD20 GUI) and headless GUI tests
#    - libsndfile1: soundfile (seedlinkToMp3)
#    - xvfb: run/verify the PyQt5 GUI without a physical display
#    - ffmpeg: seedlinkToMp3 audio encoding (usually preinstalled)
# ---------------------------------------------------------------------------
SYS_PKGS=(
  python3-venv python3-dev build-essential ffmpeg
  libsndfile1
  libgl1 libegl1 libglib2.0-0 libdbus-1-3 libxkbcommon-x11-0
  libxcb-xinerama0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1
  libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-cursor0
  xvfb x11-utils
)
if ! dpkg -s "${SYS_PKGS[@]}" >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  $SUDO apt-get update -qq
  $SUDO apt-get install -y --no-install-recommends "${SYS_PKGS[@]}"
fi

# ---------------------------------------------------------------------------
# 2. Shared Python virtualenv (PPSD backend, recvQSCD20, seedlinkToMp3)
#    numpy/obspy versions are pinned by apps/PPSD_v1/backend/requirements.txt.
#    setuptools is pinned <81 there so ObsPy 1.4's pkg_resources import works.
# ---------------------------------------------------------------------------
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip wheel
.venv/bin/pip install \
  -r apps/PPSD_v1/backend/requirements.txt \
  -r apps/recvQSCD20/requirements.txt \
  -r apps/earthworm_web/backend/requirements.txt \
  scipy==1.13.1 soundfile==0.12.1 requests==2.32.3 pytest==8.3.4 markdown==3.7

# ---------------------------------------------------------------------------
# 3. Node dependencies
#    ringserver uses vite 8 with a compatible plugin, so a normal install works.
#    apps/PPSD_v1/frontend pins vite ^8 while @vitejs/plugin-react ^4 only declares a
#    peer range up to vite 7, so --legacy-peer-deps is required (the build works
#    with vite 8 in practice). This does not modify the repo's pinned versions.
# ---------------------------------------------------------------------------
npm install --prefix apps/ringserver_seedlink_websocket
npm install --prefix apps/ringserver_seedlink_websocket/backend
npm install --prefix apps/ringserver_seedlink_websocket/frontend
npm install --prefix apps/PPSD_v1/frontend --legacy-peer-deps
npm install --prefix apps/earthworm_web/frontend
npm install --prefix apps/stationxml_manager/frontend

echo "Environment bootstrap complete."
