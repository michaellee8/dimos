#!/usr/bin/env bash
# Non-nix variant of setup.sh: build the Point-LIO substrate using SYSTEM build
# deps instead of the point_lio/flake.nix dev shell. Use this on machines without
# nix; otherwise prefer ./setup.sh. Python (numpy, matplotlib, dimos.get_data)
# comes from the dimos venv either way.
#
# Debian/Ubuntu system deps:
#   sudo apt install -y build-essential cmake libeigen3-dev libpcl-dev \
#        libyaml-cpp-dev libboost-filesystem-dev libzstd-dev
set -euo pipefail
cd "$(dirname "$0")"

# --- system build tools / native deps ---
echo ">> checking build tools..."
if ! command -v cmake >/dev/null; then
  echo "ERROR: cmake not found."
  echo "  Debian/Ubuntu: sudo apt install -y build-essential cmake libeigen3-dev \\"
  echo "                 libpcl-dev libyaml-cpp-dev libboost-filesystem-dev libzstd-dev"
  exit 1
fi

# --- dimos venv: numpy/matplotlib + dimos.get_data all live here ---
echo ">> checking dimos venv"
if ! python -c "import dimos, numpy, matplotlib" 2>/dev/null; then
  root=$(git rev-parse --show-toplevel 2>/dev/null || echo "")
  # shellcheck disable=SC1091
  [ -n "$root" ] && [ -f "$root/.venv/bin/activate" ] && . "$root/.venv/bin/activate"
fi
python -c "import dimos, numpy, matplotlib" || {
  echo "ERROR: dimos venv not available. Activate your dimos venv (numpy, matplotlib, dimos)."; exit 1; }

# --- build the Point-LIO substrate (fixed; not edited by the agent) ---
echo ">> building point_lio"
cmake -S point_lio -B point_lio/build -DCMAKE_BUILD_TYPE=Release >/dev/null
cmake --build point_lio/build -j"$(nproc 2>/dev/null || echo 4)"

# --- sanity check (pulls the data via get_data on first run) ---
echo ">> data + harness check"
python evaluate.py
echo ">> setup done. Run a baseline with:  python algo.py > run.log 2>&1"
