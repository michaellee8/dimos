#!/usr/bin/env bash
# Replay a Livox Mid-360 pcap through FAST-LIO over the wire, recording odometry
# + lidar into a memory2 db.
#
# virtual_mid360 stands up a fake Mid-360 on a virtual NIC and replays the pcap
# with a synthesized SDK2 handshake; FastLio2 connects to it as if to real
# hardware (live SDK mode) and never knows the sensor is synthetic. This is the
# only replay path — the fastlio binary has no in-process pcap reader. Use it to
# reproduce divergence / non-divergence exactly as the robot would see it.
#
# Two network namespaces joined by a veth: the lidar ns runs virtual_mid360, the
# drv ns runs `pcap_to_db` (FastLio2 live + FastLio2Recorder). Needs root for the
# netns/veth setup — set $SUDO to your privilege-escalation command (default
# `sudo`; it must run `ip`/`pkill` without a password prompt).
#
# The netns + veth NAMES are distinct from pointlio's harness (drv/lidar +
# veth-drv/veth-lidar) so the two can run concurrently. Override via env
# (DRV_NS/LIDAR_NS/VETH_DRV/VETH_LIDAR). IPs live inside each netns, so the
# .1.x addresses don't conflict with pointlio's even though they're the same.
#
# Usage:
#   source <venv>/bin/activate            # provide a python with dimos installed
#   replay_via_virtual_mid360.sh <pcap> <out.db> [duration_sec] [fastlio_config.yaml]
#
set -u
PCAP="${1:?usage: replay_via_virtual_mid360.sh <pcap> <out.db> [duration] [config.yaml]}"
DB="${2:?missing <out.db>}"
DUR="${3:-200}"
CONFIG="${4:-}"

SUDO="${SUDO:-sudo}"
HOST_IP=192.168.1.5
LIDAR_IP=192.168.1.155
DRV_NS="${DRV_NS:-fl_drv}"
LIDAR_NS="${LIDAR_NS:-fl_lidar}"
VETH_DRV="${VETH_DRV:-veth-fl-drv}"
VETH_LIDAR="${VETH_LIDAR:-veth-fl-lidar}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../../../.." && pwd)"
VM="$REPO/dimos/hardware/sensors/lidar/livox/virtual_mid360/result/bin/virtual_mid360"
PYTHON="${PYTHON:-$(command -v python)}"
VM_LOG="${VM_LOG:-/tmp/vmid360_vm.log}"
FL_LOG="${FL_LOG:-/tmp/vmid360_fastlio.log}"

[ -x "$VM" ] || { echo "missing virtual_mid360 binary at $VM — build it: (cd $(dirname "$VM")/.. && nix build .#default)"; exit 2; }
[ -f "$PCAP" ] || { echo "missing pcap: $PCAP"; exit 2; }
[ -n "$PYTHON" ] || { echo "no python on PATH — activate the dimos venv first"; exit 2; }

cleanup() {
    # Match the binary path, NOT a bare "virtual_mid360" — this script's own name
    # contains that string, so a loose pattern would SIGKILL the wrapper itself.
    $SUDO pkill -9 -f "result/bin/virtual_mid360" 2>/dev/null
    $SUDO ip netns del "$DRV_NS" 2>/dev/null
    $SUDO ip netns del "$LIDAR_NS" 2>/dev/null
    $SUDO ip link del "$VETH_DRV" 2>/dev/null
}
cleanup
$SUDO ip netns add "$DRV_NS"; $SUDO ip netns add "$LIDAR_NS"
$SUDO ip link add "$VETH_DRV" type veth peer name "$VETH_LIDAR"
$SUDO ip link set "$VETH_DRV" netns "$DRV_NS"; $SUDO ip link set "$VETH_LIDAR" netns "$LIDAR_NS"
$SUDO ip netns exec "$DRV_NS"   ip addr add "$HOST_IP/24"  dev "$VETH_DRV"
$SUDO ip netns exec "$LIDAR_NS" ip addr add "$LIDAR_IP/24" dev "$VETH_LIDAR"
for NS in "$DRV_NS" "$LIDAR_NS"; do
    $SUDO ip netns exec "$NS" ip link set lo up
    $SUDO ip netns exec "$NS" ip link set lo multicast on
    $SUDO ip netns exec "$NS" ip route add 224.0.0.0/4 dev lo
done
$SUDO ip netns exec "$DRV_NS" ip link set "$VETH_DRV" up; $SUDO ip netns exec "$LIDAR_NS" ip link set "$VETH_LIDAR" up
$SUDO ip netns exec "$DRV_NS" ip link set "$VETH_DRV" multicast on; $SUDO ip netns exec "$LIDAR_NS" ip link set "$VETH_LIDAR" multicast on
$SUDO ip netns exec "$LIDAR_NS" ip route add 255.255.255.255/32 dev "$VETH_LIDAR"
# Mid-360 multicasts point/IMU to 224.1.1.5 — egress the virtual NIC.
$SUDO ip netns exec "$LIDAR_NS" ip route add 224.1.1.5/32 dev "$VETH_LIDAR"

# Consumer: FastLio2 (live SDK) + FastLio2Recorder, recording into the db.
CFG_ARG=(); [ -n "$CONFIG" ] && CFG_ARG=(--config "$CONFIG")
$SUDO ip netns exec "$DRV_NS" env "PYTHONPATH=$REPO" "$PYTHON" \
    -m dimos.hardware.sensors.lidar.fastlio2.tools.pcap_to_db \
    --db "$DB" --duration "$DUR" --force "${CFG_ARG[@]}" > "$FL_LOG" 2>&1 &
CONSUMER=$!
sleep 5  # let the coordinator boot + open the SDK sockets

# Fake lidar: replay the pcap over the wire (delay lets the consumer settle).
echo "{\"topics\":{},\"config\":{\"pcap\":\"$PCAP\",\"rate\":1.0,\"delay\":2.0,\"lidar_netns\":\"$LIDAR_NS\"}}" \
    | $SUDO ip netns exec "$LIDAR_NS" "$VM" > "$VM_LOG" 2>&1 &

wait "$CONSUMER"
RC=$?
echo "=== handshake marker (vm log) ==="; grep -i "arming data stream\|0x0100" "$VM_LOG" | tail -1
cleanup
echo "DONE rc=$RC db=$DB"
exit "$RC"
