#!/bin/bash
# One-command R1 Lite blueprint launcher — run on the LAPTOP (not in the
# container, not on the robot).
#
#   ./scripts/r1lite_test/run_r1lite.sh                    # r1lite-coordinator
#   ./scripts/r1lite_test/run_r1lite.sh r1lite-keyboard-teleop
#
# Does three things:
#   1. Starts the rerun viewer on the laptop (port 9877) if not already up.
#      Viewer must run on the HOST: launching GUIs inside the container
#      fails (X11 auth + software-GL crashes — see BRINGUP_LOG Day 3).
#      Install once with: uv tool install rerun-sdk==0.29.2
#   2. Ensures the dev container is running.
#   3. Runs the blueprint inside the container with VIEWER=rerun-connect,
#      so the bridge streams to the laptop viewer (host networking makes
#      127.0.0.1:9877 the same place for both).
#
# Robot-side prerequisites are NOT handled here (stack up, RC mode 5 for
# chassis) — see RUNBOOK.md.

set -e

BLUEPRINT="${1:-r1lite-coordinator}"

RERUN_BIN="$(command -v rerun || echo "$HOME/.local/bin/rerun")"
if ! ss -tln | grep -q ':9877 '; then
    if [ -x "$RERUN_BIN" ]; then
        echo "[run_r1lite] starting rerun viewer on :9877"
        ("$RERUN_BIN" --port 9877 >/dev/null 2>&1 &)
        sleep 2
    else
        echo "[run_r1lite] WARNING: rerun not found on host — install with:"
        echo "    uv tool install rerun-sdk==0.29.2"
        echo "continuing headless (viewer panes will not appear)"
    fi
else
    echo "[run_r1lite] rerun viewer already up on :9877"
fi

docker start dimos-dev-r1lite >/dev/null 2>&1 || true

echo "[run_r1lite] launching $BLUEPRINT in container (Ctrl-C stops it)"
exec docker exec -it dimos-dev-r1lite bash -c "
    cd /app &&
    source .venv/bin/activate &&
    source /opt/ros/humble/setup.bash &&
    export ROS_DOMAIN_ID=2 &&
    export VIEWER=rerun-connect &&
    dimos run $BLUEPRINT
"
