---
title: "How to Integrate a New Manipulator Arm"
---
An **adapter** is the driver DimOS uses to talk to your arm. You write one class. The `ControlCoordinator` calls it in a loop, and everything else — planning, teleop, pick-and-place — works without knowing what arm you have.

Start here, because the rest of the guide follows from it.

## How your adapter gets used

The coordinator owns a 100Hz loop. Your adapter never runs a thread, never owns a socket, never publishes anything. It just answers calls.

On startup:

```
adapter.connect()            # return False and the coordinator gives up
adapter.write_enable(True)   # if auto_enable is set
```

Then, every tick, forever:

```
positions  = adapter.read_joint_positions()    # list[float], radians
velocities = adapter.read_joint_velocities()   # list[float], rad/s
efforts    = adapter.read_joint_efforts()      # list[float], Nm

        ... the coordinator runs tasks, resolves conflicts, produces commands ...

adapter.set_control_mode(mode)                 # only when the mode changes
adapter.write_joint_positions([...])           # POSITION / SERVO_POSITION
adapter.write_joint_velocities([...])          # VELOCITY
```

And on shutdown, `adapter.disconnect()`.

That is the whole live path: eleven methods, counting the gripper. The Protocol declares 26. The other fifteen are diagnostics and optional features, and every one of them may return `None` or `False` forever without anything breaking.

## What the loop implies

Three rules fall straight out of the code above, and they are the only ones you need to hold in your head.

**Return lists in your joint order, always the same length.** The coordinator does `positions[i]` against the joint list you declared. If your SDK has no velocity or torque feedback, return `[0.0] * dof` — not `[]`, not `None`. An empty list is an `IndexError` on the next tick.

**Everything is SI.** Radians, meters, rad/s, Nm. These values go straight into the planner and the IK solver, which assume radians. If your SDK speaks degrees, convert in the adapter. That is what the adapter is *for*.

**Never raise.** If your arm has no force-torque sensor, `read_force_torque()` returns `None`. If it cannot do velocity control, `write_joint_velocities()` returns `False`. The coordinator handles both. An exception on the tick thread is not handled.

## Joint names, and why they have a slash

`read_state` hands the coordinator a dict keyed by joint name, and the coordinator merges **every** piece of hardware into one namespace. Two arms both have a `joint1`, so the hardware id is the prefix that keeps them apart:

```python
make_joints("left_arm", 6)   # ['left_arm/joint1', ... 'left_arm/joint6']
make_joints("right_arm", 6)  # ['right_arm/joint1', ...]
```

That is all the slash is. Call `make_joints` and it is handled; you never type a joint name yourself.

## Writing the adapter

Copy `dimos/hardware/manipulators/mock/adapter.py`. It implements all 26 methods against fake state, so it is a working adapter with the vendor calls missing. Replace those with your SDK, method by method.

The ones that matter look like this. Here is `read_joint_positions` for an SDK that speaks degrees:

```python skip
def read_joint_positions(self) -> list[float]:
    if not self._sdk:
        raise RuntimeError("not connected")
    raw = self._sdk.get_joint_positions()          # SDK gives degrees
    return [math.radians(p) for p in raw[:self._dof]]   # DimOS wants radians
```

Two constructor details, both of which the coordinator depends on:

```python skip
class YourArmAdapter:
    def __init__(
        self,
        address: str = "192.168.1.100",
        dof: int = 6,
        initial_positions: list[float] | None = None,
        **_: object,       # the coordinator also passes hardware_id and adapter_kwargs
    ) -> None:
        ...

    def connect(self) -> bool:
        try:
            from yourarm_sdk import YourArmSDK     # import here, not at module scope
            ...
```

The `**_: object` is because the coordinator constructs every adapter the same way and passes keys yours may not care about. The lazy SDK import is so `import dimos` still works on a machine that has never seen your arm.

For a real adapter with a vendor SDK, read `dimos/hardware/manipulators/a750/adapter.py`. If your arm has no Python SDK and you are talking to a raw bus, `openarm/` drives SocketCAN directly.

## Registering it

Two places. A manifest next to your adapter:

```python skip
# dimos/hardware/manipulators/yourarm/_registry.py
ADAPTER_FACTORIES = {
    "yourarm": "dimos.hardware.manipulators.yourarm.adapter:YourArmAdapter",
}
```

Keep it to stdlib imports. It gets loaded on machines that do not have your vendor SDK, which is what makes a missing SDK fail with a clear error at `create()` instead of your arm silently vanishing from the list.

Then add your name to `EXPECTED_NAMES` in `dimos/hardware/test_adapter_registries.py`. CI pins the exact set of registered adapters on purpose, so adding one is a deliberate act rather than an accident.

## Wiring it up

Two more files, both small. First, describe the arm — `dimos/robot/manipulators/yourarm/config.py`:

```python skip
def yourarm_hardware(hw_id: str = "arm") -> HardwareComponent:
    return HardwareComponent(
        hardware_id=hw_id,
        hardware_type=HardwareType.MANIPULATOR,
        joints=make_joints(hw_id, 6),
        adapter_type="yourarm",                 # matches the ADAPTER_FACTORIES key
        address="192.168.1.100",                # handed to your __init__
        gripper_joints=[f"{hw_id}/gripper"],    # driven via write_gripper_position
    )
```

Then make it runnable — `dimos/robot/manipulators/yourarm/blueprints/basic.py`:

```python skip
_hw = yourarm_hardware("arm")

coordinator_yourarm = autoconnect(
    coordinator(hardware=[_hw], tasks=[trajectory_task(_hw)]),
)
```

`autoconnect` wires modules together by matching their ports. It also has a second job: `dimos/robot/all_blueprints.py` is generated by scanning for assignments from `autoconnect(...)` or `.blueprint(...)`, so it is what gives your blueprint a name on the CLI. A blueprint built any other way works fine in Python but `dimos run` will not find it.

Copy the shape from `dimos/robot/manipulators/a750/blueprints/teleop.py` and you inherit all of this.

## Running it

```bash
pytest dimos/robot/test_all_blueprints_generation.py   # regenerates all_blueprints.py; commit the result
dimos run coordinator-yourarm
```

You do not need the hardware to do this. Set `adapter_type="mock"` and the entire coordinator, planner, and teleop stack runs against the mock adapter. Get that working first — it is how the shipped arms are tested, and it means the only thing left to debug on the real robot is your SDK calls.

## Going further

Motion planning needs a URDF and a `RobotModelConfig`. Cartesian control, keyboard teleop, and VR teleop each add a different task to the coordinator. All of it, with templates and a verification loop, is in [Adding a New Arm](/docs/coding-agents/adding_a_new_arm.md).

`dimos/hardware/manipulators/README.md` is the quick reference for the adapter tree. For a full integration written up end to end, including the CAN debugging, see [OpenArm Integration](/docs/capabilities/manipulation/openarm_integration.md).
