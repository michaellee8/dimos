# OpenArm Mini Teleop

OpenArm Mini teleop uses the Feetech leader arms directly and publishes OpenArm
follower `JointState` commands through the generic teleop runtime. It does not
depend on LeRobot at runtime.

## Install optional dependencies

```bash
uv sync --extra openarm
# or only the leader teleop SDK
uv sync --extra openarm-mini-teleop
```

The Feetech package installs as `ftservo-python-sdk` and imports as
`scservo_sdk`.

## Calibration storage

Runtime startup is non-interactive. Create calibration artifacts before running
the teleop blueprint. Defaults are side-specific directories:

- left: `STATE_DIR / "teleop" / "openarm_mini" / "left" / "calibration.json"`
- right: `STATE_DIR / "teleop" / "openarm_mini" / "right" / "calibration.json"`

`STATE_DIR` is DimOS' XDG state directory, typically
`~/.local/state/dimos` on Linux.

## Manual calibration

Run the demo script with the OpenArm Mini leader connected. The script only
opens the leader Feetech serial ports; it never starts `ControlCoordinator` and
never connects follower OpenArm hardware.

Before calibration, place the selected leader side in its natural zero pose: the
pose designed to correspond to the OpenArm follower's all-zero arm-joint
configuration. Calibration reads arm motors `joint_1` through `joint_7` once and
writes those raw positions as `homing_offset` values. Motor 8 / gripper is not
read or stored in v1 because the OpenArm follower gripper is not yet exposed as a
formal coordinator-controllable API.

```bash
python -m dimos.teleop.openarm_mini.demo_calibrate_openarm_mini \
  --side both \
  --port-left /dev/ttyUSB1 \
  --port-right /dev/ttyUSB0
```

The script prints a confirmation table with each semantic arm joint, physical
Feetech motor id, captured raw zero offset, and `flip` value before writing the
artifact. Calibration artifacts are strict arm-only JSON with exactly
`joint_1`...`joint_7`, each containing only:

- `id`: physical Feetech motor id for that semantic leader joint
- `homing_offset`: raw tick value captured in the leader zero pose
- `flip`: whether to negate the calibrated radians for that joint

Default flip sets match the known OpenArm Mini leader orientation. Override them
when needed:

```bash
python -m dimos.teleop.openarm_mini.demo_calibrate_openarm_mini \
  --side left \
  --port-left /dev/ttyUSB1 \
  --left-flips joint_1,joint_3,joint_4,joint_5,joint_6,joint_7
```

Use `--left-flips none` or `--right-flips none` to record no flipped joints.

At runtime, raw Feetech ticks convert to radians around the captured zero using
the full Feetech encoder span, then per-joint `flip` is applied. The adapter maps
semantic leader joints directly to OpenArm follower arm-joint names and clamps
outgoing positions to OpenArm follower joint limits before publishing. The
operator must still align the follower near the leader-implied command before
enabling teleop authority; automatic startup alignment gating is out of scope for
v1.

To inspect calibrated leader readings without starting robot control:

```bash
python -m dimos.teleop.openarm_mini.demo_calibrate_openarm_mini \
  --side left \
  --port-left /dev/ttyUSB1 \
  --live-readout
```

For a Rich terminal UI that continuously displays raw ticks, calibrated radians,
sender-side clamped follower radians, motor ids, and flip values:

```bash
python -m dimos.teleop.openarm_mini.demo_joint_tui_openarm_mini \
  --side both \
  --port-left /dev/ttyUSB1 \
  --port-right /dev/ttyUSB0
```

The TUI is also leader-only: it reads OpenArm Mini Feetech ports and existing
calibration files, but does not start `ControlCoordinator` or connect follower
OpenArm hardware.

Use `--left-calibration-path` and `--right-calibration-path` to write or read
non-default calibration directories.
