# R1 Lite Session Runbook

Everything validated 2026-07-02/03, with exact recreate commands.
Consoles: **[laptop]** = plain laptop shell · **[robot]** = `ssh r1lite` ·
**[container]** = shell inside `dimos-dev-r1lite`.

---

## One-time setup (already done — recorded for rebuild-from-scratch)

| What | Command | Status |
|---|---|---|
| ghcr access (needs `read:packages`) | `gh auth refresh -h github.com -s read:packages` then `gh auth token \| docker login ghcr.io -u KrishnaH96 --password-stdin` | ✅ |
| Pull ROS-track dev image (NOT `dev:latest` — that one has no ROS) | `docker pull ghcr.io/dimensionalos/ros-dev:dev` | ✅ |
| Create container | `docker run -d --name dimos-dev-r1lite --network host -v /home/krishnah/krishnah/dimos:/app -v /tmp/.X11-unix:/tmp/.X11-unix -v $HOME/.Xauthority:/root/.Xauthority:rw -e PYTHONUNBUFFERED=1 -e PYTHONPATH=/app -e DISPLAY=$DISPLAY -it ghcr.io/dimensionalos/ros-dev:dev /bin/bash` | ✅ |
| Rebuild venv as py3.10 (Humble/rclpy) — in container | `cd /app && ln -sf .envrc.r1pro .envrc && rm -rf .venv && UV_PYTHON=3.10 uv sync --all-extras --no-extra dds --no-extra unitree-dds` | ✅ |
| SSH alias + key | `~/.ssh/config` Host `r1lite` → `r1lite@192.168.1.85`; `ssh-copy-id r1lite` (password: `1`) | ✅ |
| Persistent laptop IP (2026-07-03) | `nmcli connection modify lidar +ipv4.addresses 10.42.0.100/24` — "lidar" profile now carries 192.168.1.5 AND 10.42.0.100 on every link-up | ✅ |

## Every-session bring-up

1. **[laptop] Verify cable link** (IP is persistent since 2026-07-03 — no nmcli needed):
   ```bash
   ping -c 2 10.42.0.2        # robot onboard PC over the cable
   ```
2. **[laptop] Container** (after reboot/suspend):
   ```bash
   docker start dimos-dev-r1lite
   docker exec -it dimos-dev-r1lite bash      # one per terminal needed
   ```
3. **[container] Per-shell env** (every new shell):
   ```bash
   source .venv/bin/activate && source /opt/ros/humble/setup.bash && export ROS_DOMAIN_ID=2
   ```
4. **[robot] Stack** (if `tmux ls` shows nothing):
   ```bash
   cd ~/galaxea/install/startup_config/share/startup_config/script
   ./robot_startup.sh boot ../sessions.d/ATCStandard/R1LITEBody.d
   # wait ~30s (arms/grippers twitch = HDAS health sign), then:
   tmux kill-session -t r1lite_teleop     # keep GELLO teleop off the arms
   ```
   Shutdown: `./robot_startup.sh kill`

## Validated tests (all ✅, safe to recreate)

**Discovery / read-only:**
```bash
# [container] full graph recon (topics, nodes, rates, DOF):
python scripts/r1lite_test/test_00_recon.py

# [container] formal topic assertion (12 expected topics):
python scripts/r1lite_test/test_01_topic_discovery.py

# [container] live position of any segment:
ros2 topic echo /hdas/feedback_arm_left --field position
# ("A message was lost!!!" spam on 200-488Hz topics = slow CLI subscriber, benign)
```

**Gripper (first actuation ✅ — 0–100 units, 0=closed, 100=open):**
```bash
# [container] shell B monitor:
ros2 topic echo /hdas/feedback_gripper_left --field position
# [container] shell A — MUST STREAM (-r 10); one-shot --once is ignored.
# Motion stops the moment you Ctrl-C (dead-man).
ros2 topic pub -r 10 /motion_target/target_position_gripper_left sensor_msgs/msg/JointState "{header: {stamp: now}, name: [''], position: [85.0], velocity: [0.0], effort: [0.0]}"
# reopen: same with position: [101.8]
```

**Arm wrist-roll (✅ — serial joints, independently commandable):**
```bash
# [container] shell B monitor:
ros2 topic echo /hdas/feedback_arm_left --field position
# [container] shell A — joints 1-5 held at rest values, joint 6 → 0.2 rad:
ros2 topic pub -r 10 /motion_target/target_joint_state_arm_left sensor_msgs/msg/JointState "{header: {stamp: now}, name: [''], position: [0.065, 0.0, 0.0, 0.008, -0.001, 0.2], velocity: [0.5, 0.5, 0.5, 0.5, 0.5, 0.5], effort: [0.0]}"
# return home: same with last value 0.001
```

## NEVER recreate

- **Torso joint targets** (`target_joint_state_torso`) — parallelogram
  linkage; single-joint deltas made the robot SHAKE (2026-07-03).
  Galaxea docs: joint+velocity torso signals conflict, disable_torso=true
  by default. test_06 is hard-guarded. Torso motion later = task-space
  `target_speed_torso` only, as a designed experiment.
- **`findrobot_server.sh` on the robot** — rewrites DDS config to
  discovery-server mode and reboots; would break our multicast setup.

## Chassis: partially solved, one blocker (see BRINGUP_LOG for full saga)

Validated: chassis node accepts streamed targets in RC **mode 5** (RC ON,
all 4 switches position 1), ramp reaches full speed with acc_limit +
brake=false streamed (test_03 does all gates itself). RC mode map:
all-pos1=5 (software), sw1@2+sw2@3=2 (brake), +sw3@mid=3 (RC manual drive).

UNRESOLVED: wheels refuse to turn (both software AND RC manual) despite
healthy RC/VCU/battery/e-stop. **Next session, check FIRST: the separate
wireless E-STOP REMOTE** (R1 Lite ships 3 remotes: torso/chassis/e-stop —
a pressed or dead e-stop fob = failsafe stop, explains everything).
Fallbacks: Galaxea "Wheel Motor Zero-Point Calibration" doc,
product@galaxea-dynamics.com.

⚠️ RULES learned the hard way:
- Chassis node LATCHES the last target forever (no dead-man!) — ALWAYS
  end chassis work with a zero-velocity stream.
- Never power the robot on with e-stop pressed (whole-session inhibit).
- On-robot `ros2 topic list/echo` may show nothing after `ros2 daemon
  stop` — daemon cache warming, not an outage; wait or use --no-daemon.

## Not yet done

- Chassis wheel-level unblock (e-stop remote lead above), then test_03 PASS.
- Torso task-space experiment (target_speed_torso, MPC path) — designed
  session; joint path is guarded off.
- Mesh copy for LFS: `scp -r r1lite:~/galaxea/install/mobiman/share/mobiman/urdf/R1_Lite/meshes /tmp/`
- `R1LiteConnection` module (all facts in `r1lite_config.py`).
