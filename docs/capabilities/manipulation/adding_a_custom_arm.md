---
title: "How to Integrate a New Manipulator Arm"
---
DimOS talks to every arm through one small class: an **adapter**. It wraps your vendor's SDK and answers a fixed set of questions — where are the joints right now, go to these angles, open the gripper.

Write that one class and the rest of the stack comes free. Motion planning, keyboard and VR teleop, pick-and-place, the LLM agent: none of them know or care what arm you have. They all talk to the coordinator, and the coordinator talks to your adapter.

It is usually about 200 lines.

## Where the adapter sits

```
ControlCoordinator      100Hz loop. Runs tasks, decides which task
                        commands which joint, produces one command set.
        │
        │  calls your methods
        ▼
Your adapter            Turns those calls into vendor SDK calls,
                        and vendor units into SI.
        │
        ▼
The arm
```

Your adapter owns no threads, no sockets, and no message ports. It is entirely passive: the coordinator calls it, it answers. That is the whole design, and it is why an adapter stays small.

## What the coordinator asks for

On startup it calls `connect()`, then `write_enable(True)`. Then, every tick, forever:

```
positions  = adapter.read_joint_positions()     # radians
velocities = adapter.read_joint_velocities()    # rad/s
efforts    = adapter.read_joint_efforts()       # Nm

     ... the coordinator runs its tasks and resolves conflicts ...

adapter.set_control_mode(mode)                  # only when it changes
adapter.write_joint_positions([...])            # or write_joint_velocities
```

On shutdown, `disconnect()`.

That is the entire live path. The Protocol declares 26 methods, but only eleven are ever called in normal operation. The other fifteen are diagnostics and optional features that can return `None` or `False` forever without anything noticing.

So the job is smaller than the Protocol makes it look.

## Building the adapter

Copy `dimos/hardware/manipulators/mock/adapter.py`. It implements all 26 methods against in-memory fake state, which makes it a complete, working adapter with the vendor calls missing. Your job is to replace the fakes.

There is no base class and nothing to inherit from. The Protocol is duck-typed: match the method names and DimOS accepts it.

### Connecting

Return `True` on success, `False` on failure. Do not raise, or you take the coordinator down with you.

```python skip
def connect(self) -> bool:
    try:
        from yourarm_sdk import YourArmSDK
        self._sdk = YourArmSDK(self._address)
        self._sdk.connect()
        return bool(self._sdk.is_alive())
    except Exception as e:
        logger.error(f"could not reach arm at {self._address}: {e}")
        return False
```

Import the SDK **inside** `connect()`, not at the top of the file. Vendor SDKs are optional dependencies, and a module-scope import means `import dimos` explodes on every machine that does not have your arm plugged in.

### Reading state

This is where unit conversion lives. Most vendor SDKs speak degrees. DimOS speaks radians, and those numbers flow straight into the IK solver.

```python skip
def read_joint_positions(self) -> list[float]:
    raw = self._sdk.get_joint_positions()               # degrees, from the SDK
    return [math.radians(p) for p in raw[:self._dof]]   # radians, for DimOS
```

The coordinator reads these lists **positionally** — `positions[i]` against the joint list you declared. They must be `dof` long, in your joint order, every tick.

That matters most for the feedback your arm probably does not have:

```python skip
def read_joint_velocities(self) -> list[float]:
    return [0.0] * self._dof     # no velocity feedback? zeros. Not [], not None.
```

Return an empty list and you get an `IndexError` on the next tick. Zeros are correct, and the coordinator handles them fine.

### Writing commands

The coordinator hands you a full, ordered list of targets. Convert and forward.

```python skip
def write_joint_positions(self, positions: list[float], velocity: float = 1.0) -> bool:
    degrees = [math.degrees(p) for p in positions]
    return self._sdk.set_joint_positions(degrees)
```

`set_control_mode` is called only when the mode actually changes. Map DimOS's modes onto your SDK's, and return `False` for any you do not support:

```python skip
def set_control_mode(self, mode: ControlMode) -> bool:
    sdk_mode = {
        ControlMode.POSITION: 0,
        ControlMode.SERVO_POSITION: 1,   # high-frequency streaming
        ControlMode.VELOCITY: 4,
    }.get(mode)
    if sdk_mode is None:
        return False                     # unsupported. The coordinator copes.
    return self._sdk.set_mode(sdk_mode)
```

### The gripper

Grippers are not joints. They get their own two methods, in **meters** of opening:

```python skip
def read_gripper_position(self) -> float | None:
    return self._sdk.get_gripper_mm() / 1000.0

def write_gripper_position(self, position: float) -> bool:
    return self._sdk.set_gripper_mm(position * 1000.0)
```

No gripper? Return `None` and `False`, and you are done.

### What you can skip

Roughly half the Protocol. No force-torque sensor, no Cartesian mode, no error codes — say so and move on:

```python skip
def read_force_torque(self) -> list[float] | None:
    return None                  # no sensor

def write_cartesian_position(self, pose, velocity: float = 1.0) -> bool:
    return False                 # not supported
```

The rule throughout: **unsupported reads return `None`, unsupported writes return `False`, and nothing ever raises.** An exception on the tick thread is not caught.

### The constructor

One detail that is easy to miss and will bite you on startup:

```python skip
def __init__(
    self,
    address: str = "192.168.1.100",
    dof: int = 6,
    initial_positions: list[float] | None = None,
    **_: object,          # <- this
) -> None:
```

The coordinator builds every adapter identically, passing `address`, `dof`, `hardware_id`, and whatever else the blueprint specifies. The `**_: object` swallows the keys yours does not use. Without it, `TypeError`.

For a finished adapter with a real vendor SDK, read `dimos/hardware/manipulators/a750/adapter.py`. If your arm has no Python SDK at all and you are down at the bus level, `openarm/` drives raw SocketCAN.

## Registering it

Drop a manifest beside your adapter so DimOS can find it:

```python skip
# dimos/hardware/manipulators/yourarm/_registry.py
ADAPTER_FACTORIES = {
    "yourarm": "dimos.hardware.manipulators.yourarm.adapter:YourArmAdapter",
}
```

Stdlib imports only in that file. It loads even on machines without your vendor SDK, which is what makes a missing SDK fail with a clear message instead of your arm quietly vanishing from the list.

Then add `"yourarm"` to `EXPECTED_NAMES` in `dimos/hardware/test_adapter_registries.py`. CI pins the exact set of adapters on purpose, so adding one is deliberate rather than accidental.

## Running it

Two small files under `dimos/robot/manipulators/yourarm/`. One describes the arm, one makes it runnable.

```python skip
# config.py
def yourarm_hardware(hw_id: str = "arm") -> HardwareComponent:
    return HardwareComponent(
        hardware_id=hw_id,
        hardware_type=HardwareType.MANIPULATOR,
        joints=make_joints(hw_id, 6),           # ['arm/joint1', ... 'arm/joint6']
        adapter_type="yourarm",                 # matches your ADAPTER_FACTORIES key
        address="192.168.1.100",                # handed to your __init__
        gripper_joints=[f"{hw_id}/gripper"],
    )

# blueprints/basic.py
_hw = yourarm_hardware("arm")

coordinator_yourarm = autoconnect(
    coordinator(hardware=[_hw], tasks=[trajectory_task(_hw)]),
)
```

`autoconnect` connects modules by matching their ports, and it is also what lands your blueprint in `dimos/robot/all_blueprints.py`, which is generated by scanning for exactly that call. Build a blueprint another way and it will work fine in Python, but `dimos run` will never find it.

```bash
pytest dimos/robot/test_all_blueprints_generation.py   # regenerates the registry; commit the result
dimos run coordinator-yourarm
```

**You do not need the arm for any of this.** Set `adapter_type="mock"` and the whole stack — coordinator, planner, teleop — runs against the mock adapter. Build against that first. It is how the shipped arms are tested, and it means the only thing left to debug on real hardware is your SDK calls.

## Going further

Motion planning needs a URDF and a `RobotModelConfig`. Cartesian control, keyboard teleop, and VR teleop each add a task to the coordinator. All of that is in [Adding a New Arm](/docs/coding-agents/adding_a_new_arm.md), the full reference, and the page to hand an AI agent.

For an integration written up end to end, including the CAN debugging, see [OpenArm Integration](/docs/capabilities/manipulation/openarm_integration.md).
